"""E2E CLI tests for A-01 ``normocontrol run``."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unicodedata import normalize

import fitz
import pytest
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.domain import ExitCode
from normocontrol.orchestrator import OrchestratorHooks, run_pipeline
from normocontrol.reporting.json_report import load_report_schema, validate_published_report
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
DEMO_PASS = ROOT / "tests" / "fixtures" / "demo" / "pass"
DEMO_FAIL = ROOT / "tests" / "fixtures" / "demo" / "fail"
RUBRIC = ROOT / "rubric.yaml"
CONFIG = ROOT / "normocontrol.yaml.example"

runner = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TOP_LEVEL_FINDING_RE = re.compile(r"(?m)^- \*\*[A-Z]{3}-\d{2}\*\*")
_GLUED_FINDING_RE = re.compile(r"[^\r\n]- \*\*[A-Z]{3}-\d{2}\*\*")
_TRUNCATED_GLUE_RE = re.compile(r"\[TRUNCATED\]- \*\*")


def _plain(text: str) -> str:
    """Strip ANSI; Typer Rich help splits ``--out`` across color spans under GITHUB_ACTIONS."""
    return _ANSI_RE.sub("", text)


def _assert_report_findings_are_separated(markdown: str) -> None:
    assert _TOP_LEVEL_FINDING_RE.search(markdown) is not None
    assert _GLUED_FINDING_RE.search(markdown) is None
    assert _TRUNCATED_GLUE_RE.search(markdown) is None


class _SuccessBuild(LatexBuildService):
    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root, main_tex
        return LatexBuildResult(
            status=LatexBuildStatus.SUCCESS,
            returncode=0,
            log_excerpt="mock ok",
        )


@pytest.fixture(autouse=True)
def _mock_build(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_pipeline(request, hooks=None):  # type: ignore[no-untyped-def]
        del hooks
        return run_pipeline(request, OrchestratorHooks(build_service=_SuccessBuild()))

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)


def test_run_help_lists_options(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI sets GITHUB_ACTIONS → Typer Rich colors; highlighter splits ``--out`` across spans.
    import typer.rich_utils as rich_utils

    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", True)
    result = runner.invoke(cli.app, ["run", "--help"])
    assert result.exit_code == 0
    help_text = _plain(result.stdout)
    assert "--out" in help_text
    assert "--only" in help_text
    assert "--final" in help_text
    assert "--model" in help_text
    assert "--base-url" in help_text


def test_run_pass_demo_exit_zero(tmp_path: Path) -> None:
    out = tmp_path / "pass"
    before = datetime.now(UTC).replace(microsecond=0)
    result = runner.invoke(
        cli.app,
        [
            "--no-llm",
            "run",
            str(DEMO_PASS),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out),
        ],
    )
    after = datetime.now(UTC).replace(microsecond=0)
    assert result.exit_code == int(ExitCode.SUCCESS), result.stdout + result.stderr
    published = json.loads((out / "report.json").read_text(encoding="utf-8"))
    validate_published_report(published, schema=load_report_schema())
    assert published["exit_code"] == 0
    assert published["header"]["gate_status"] == "pass"
    generated_at = published["header"]["generated_at"]
    generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    assert before <= generated <= after
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", generated_at)
    assert (out / "report.md").is_file()
    assert (out / "summary.json").is_file()
    assert "GostCheck run summary" in result.stdout
    assert "gate: PASS" in result.stdout
    assert "degraded:" in result.stdout
    assert "counts: pass=" in result.stdout
    assert f"report.md: …/{out.name}/report.md" in result.stdout
    assert f"report.json: …/{out.name}/report.json" in result.stdout
    assert "exit_code: 0 (success; advisory findings do not block)" in result.stdout


def test_run_fail_demo_exit_two(tmp_path: Path) -> None:
    out = tmp_path / "fail"
    result = runner.invoke(
        cli.app,
        [
            "--no-llm",
            "run",
            str(DEMO_FAIL),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == int(ExitCode.FORMAL_FAILURE), result.stdout + result.stderr
    assert "gate: FAIL" in result.stdout
    assert "blocking_findings:" in result.stdout
    assert "exit_code: 2 (formal gate failed)" in result.stdout
    _assert_report_findings_are_separated((out / "report.md").read_text(encoding="utf-8"))


def test_run_unknown_only_exit_three(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "--no-llm",
            "run",
            str(DEMO_PASS),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(tmp_path / "out"),
            "--only",
            "not-a-real-prefix",
        ],
    )
    assert result.exit_code == int(ExitCode.CONFIG_ERROR)
    assert "gate: FAIL" in result.stdout
    assert "exit_code: 3 (input or configuration error)" in result.stdout
    assert "report.md:" in result.stdout
    assert "(not generated)" in result.stdout


def test_run_missing_source_exit_three(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "--no-llm",
            "run",
            str(tmp_path / "missing"),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == int(ExitCode.CONFIG_ERROR)
    assert "gate: FAIL" in result.stdout
    assert "exit_code: 3 (input or configuration error)" in result.stdout


def _run_pdf_subprocess(
    pdf_path: Path,
    out_dir: Path,
    *,
    only: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "normocontrol.cli",
            "--no-llm",
            "run",
            str(pdf_path),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out_dir),
            "--only",
            only,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_cp1251_subprocess(
    *args: str,
    path_prefix: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    env["PYTHONIOENCODING"] = "cp1251:strict"
    if path_prefix is not None:
        env["PATH"] = os.pathsep.join((str(path_prefix), env["PATH"]))
    return subprocess.run(
        [sys.executable, "-m", "normocontrol.cli", *args],
        cwd=ROOT,
        env=env,
        text=False,
        capture_output=True,
        check=False,
    )


def _decode_cp1251(output: bytes) -> str:
    return output.decode("cp1251")


def test_pdf_only_subprocess_returns_real_zero_and_two_codes(tmp_path: Path) -> None:
    passed = _run_pdf_subprocess(
        ROOT / "tests" / "fixtures" / "pdf" / "fmt_pass.pdf",
        tmp_path / "pass",
        only="FMT-01",
    )
    failed = _run_pdf_subprocess(
        ROOT / "tests" / "fixtures" / "pdf" / "fmt_wrong_font.pdf",
        tmp_path / "wrong-font",
        only="FMT-01",
    )

    assert passed.returncode == int(ExitCode.SUCCESS), passed.stdout + passed.stderr
    assert failed.returncode == int(ExitCode.FORMAL_FAILURE), failed.stdout + failed.stderr
    published = json.loads((tmp_path / "wrong-font" / "report.json").read_text(encoding="utf-8"))
    finding = next(item for item in published["findings"] if item["rule_id"] == "FMT-01")
    assert finding["path"] == "fmt_wrong_font.pdf"
    assert finding["page"] == 1
    assert finding["evidence"]
    assert "font_ratio=" in finding["evidence"][0]["description"]
    markdown = (tmp_path / "wrong-font" / "report.md").read_text(encoding="utf-8")
    assert "font_ratio=" in markdown


@pytest.mark.parametrize(
    ("filename", "rule_id"),
    [
        ("fmt_non_bold_heading.pdf", "FMT-02"),
        ("fmt_margin_overflow.pdf", "FMT-05"),
    ],
)
def test_pdf_fail_fixtures_return_two_in_subprocess(
    tmp_path: Path,
    filename: str,
    rule_id: str,
) -> None:
    result = _run_pdf_subprocess(
        ROOT / "tests" / "fixtures" / "pdf" / filename,
        tmp_path / rule_id,
        only=rule_id,
    )

    assert result.returncode == int(ExitCode.FORMAL_FAILURE), result.stdout + result.stderr
    if rule_id == "FMT-05":
        published = json.loads((tmp_path / rule_id / "report.json").read_text(encoding="utf-8"))
        finding = next(item for item in published["findings"] if item["rule_id"] == "FMT-05")
        assert finding["path"] == filename
        assert finding["page"] == 1
        assert finding["evidence"]
        assert "bounds=[" in finding["evidence"][0]["description"]
        markdown = (tmp_path / rule_id / "report.md").read_text(encoding="utf-8")
        assert "bounds=[" in markdown


def test_pdf_without_text_layer_returns_two_in_subprocess(tmp_path: Path) -> None:
    pdf_path = tmp_path / "no-text-layer.pdf"
    document = fitz.open()
    document.new_page(width=595, height=842)
    document.save(pdf_path)
    document.close()

    out_dir = tmp_path / "no-text-out"
    result = _run_pdf_subprocess(pdf_path, out_dir, only="FMT-01")

    assert result.returncode == int(ExitCode.FORMAL_FAILURE), result.stdout + result.stderr
    published = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert published["header"]["degraded"] is True
    assert published["counts"]["blocking_unverifiable"] > 0
    assert "gate: FAIL" in result.stdout
    assert "degraded: true" in result.stdout
    assert "degraded_reason: formal checks unverifiable:" in result.stdout
    assert "unverifiable=" in result.stdout


def test_run_supports_cyrillic_paths_with_spaces_and_existing_report_dir(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "Синтетическая работа с пробелами"
    source_dir.mkdir()
    source = source_dir / "Проверка шрифта.pdf"
    source.write_bytes((ROOT / "tests" / "fixtures" / "pdf" / "fmt_pass.pdf").read_bytes())
    out = tmp_path / "Каталог отчёта"

    first = runner.invoke(
        cli.app,
        [
            "--no-llm",
            "run",
            str(source),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out),
            "--only",
            "FMT-01",
        ],
    )
    second = runner.invoke(
        cli.app,
        [
            "--no-llm",
            "run",
            str(source),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out),
            "--only",
            "FMT-01",
        ],
    )

    assert first.exit_code == int(ExitCode.SUCCESS), first.stdout + first.stderr
    assert second.exit_code == int(ExitCode.SUCCESS), second.stdout + second.stderr
    assert "Проверка шрифта.pdf" in second.stdout
    assert "…/Каталог отчёта/report.md" in second.stdout
    assert "gate: PASS" in second.stdout


@pytest.mark.parametrize(
    "filename",
    [
        "ВКР_Золоева.pdf",
        "ВКР_Золое\u0308ва.pdf",
        "ВКР_а\u0301.pdf",
        "ВКР_📄.pdf",
        "ВКР_╨.pdf",
        "ВКР_╨╨╨.pdf",
    ],
)
def test_run_cp1251_subprocess_preserves_unicode_filename_and_exit_zero(
    tmp_path: Path,
    filename: str,
) -> None:
    source = tmp_path / filename
    source.write_bytes((ROOT / "tests" / "fixtures" / "pdf" / "fmt_pass.pdf").read_bytes())
    out = tmp_path / f"report-{len(filename)}"

    result = _run_cp1251_subprocess(
        "--no-llm",
        "run",
        str(source),
        "--config",
        str(CONFIG),
        "--rubric",
        str(RUBRIC),
        "--out",
        str(out),
        "--only",
        "FMT-01",
    )

    stdout = _decode_cp1251(result.stdout)
    stderr = _decode_cp1251(result.stderr)
    expected_display = (
        normalize("NFC", filename).encode("cp1251", errors="backslashreplace").decode("cp1251")
    )
    assert result.returncode == int(ExitCode.SUCCESS), stdout + stderr
    assert f"input: …/{expected_display}" in stdout
    assert source.is_file()
    assert source.name == filename
    assert "Traceback" not in stdout
    assert "sk-" not in stdout + stderr
    assert "Synthetic PDF fixture" not in stdout + stderr
    assert str(tmp_path.resolve()) not in stdout + stderr
    published = json.loads((out / "report.json").read_text(encoding="utf-8"))
    validate_published_report(published, schema=load_report_schema())
    assert published["exit_code"] == int(ExitCode.SUCCESS)


def test_run_cp1251_subprocess_preserves_written_formal_exit_two(tmp_path: Path) -> None:
    source = tmp_path / "ВКР_╨╨_📄.pdf"
    source.write_bytes((ROOT / "tests" / "fixtures" / "pdf" / "fmt_wrong_font.pdf").read_bytes())
    out = tmp_path / "formal-fail"

    result = _run_cp1251_subprocess(
        "--no-llm",
        "run",
        str(source),
        "--config",
        str(CONFIG),
        "--rubric",
        str(RUBRIC),
        "--out",
        str(out),
        "--only",
        "FMT-01",
    )

    stdout = _decode_cp1251(result.stdout)
    stderr = _decode_cp1251(result.stderr)
    assert result.returncode == int(ExitCode.FORMAL_FAILURE), stdout + stderr
    assert "Traceback" not in stdout
    assert "exit_code: 2 (formal gate failed)" in stdout
    published = json.loads((out / "report.json").read_text(encoding="utf-8"))
    validate_published_report(published, schema=load_report_schema())
    assert published["exit_code"] == int(ExitCode.FORMAL_FAILURE)


def test_run_cp1251_subprocess_configuration_error_stays_three(tmp_path: Path) -> None:
    missing = tmp_path / "нет_╨_📄.pdf"
    result = _run_cp1251_subprocess(
        "--no-llm",
        "run",
        str(missing),
        "--config",
        str(CONFIG),
        "--rubric",
        str(RUBRIC),
        "--out",
        str(tmp_path / "config-error"),
        "--only",
        "FMT-01",
    )

    stdout = _decode_cp1251(result.stdout)
    stderr = _decode_cp1251(result.stderr)
    assert result.returncode == int(ExitCode.CONFIG_ERROR), stdout + stderr
    assert "Traceback" not in stdout
    assert str(tmp_path.resolve()) not in stdout + stderr


def test_run_cp1251_subprocess_fail_closed_stays_four(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if os.name == "nt":
        fake_latexmk = bin_dir / "latexmk.exe"
        shutil.copy2(sys.executable, fake_latexmk)
    else:
        fake_latexmk = bin_dir / "latexmk"
        fake_latexmk.write_text("#!/bin/sh\nexit 1\n", encoding="ascii")
        fake_latexmk.chmod(0o755)
    source_dir = tmp_path / "сломанная_╨_📄"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        "\\documentclass{definitely-missing-synthetic-class}\n"
        "\\begin{document}\n"
        "synthetic\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    result = _run_cp1251_subprocess(
        "--no-llm",
        "run",
        str(source_dir),
        "--config",
        str(CONFIG),
        "--rubric",
        str(RUBRIC),
        "--out",
        str(tmp_path / "internal-error"),
        "--only",
        "build",
        "--fail-closed",
        path_prefix=bin_dir,
    )

    stdout = _decode_cp1251(result.stdout)
    stderr = _decode_cp1251(result.stderr)
    assert result.returncode == int(ExitCode.INTERNAL_ERROR), stdout + stderr
    assert "Traceback" not in stdout
    assert str(tmp_path.resolve()) not in stdout + stderr


@pytest.mark.parametrize("kind", ["corrupt", "encrypted"])
def test_unreadable_pdf_never_returns_pass(
    tmp_path: Path,
    kind: str,
) -> None:
    pdf_path = tmp_path / f"{kind}.pdf"
    if kind == "corrupt":
        pdf_path.write_bytes(b"%PDF-1.7\nsynthetic corrupt payload\n")
    else:
        document = fitz.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((100, 100), "Synthetic encrypted document")
        document.save(
            pdf_path,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="synthetic-owner",
            user_pw="synthetic-user",
        )
        document.close()

    result = _run_pdf_subprocess(pdf_path, tmp_path / f"{kind}-out", only="FMT-01")

    assert result.returncode == int(ExitCode.CONFIG_ERROR), result.stdout + result.stderr
    assert str(tmp_path.resolve()) not in result.stdout + result.stderr
