"""E2E CLI coverage for ``normocontrol run --gate-mode``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from normocontrol.domain import ExitCode
from normocontrol.reporting.json_report import load_report_schema, validate_published_report

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / "rubric.yaml"
CONFIG = ROOT / "normocontrol.yaml.example"
# Class-layer rules stay unverifiable on a PDF-only submission while nothing fails.
UNVERIFIABLE_PDF = ROOT / "tests" / "fixtures" / "pdf" / "fmt_pass.pdf"
FAILING_PDF = ROOT / "tests" / "fixtures" / "pdf" / "fmt_wrong_font.pdf"


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "normocontrol.cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_cli(
    out_dir: Path,
    *extra: str,
    source: Path = UNVERIFIABLE_PDF,
    config: Path = CONFIG,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    result = _cli(
        "--no-llm",
        "run",
        str(source),
        "--config",
        str(config),
        "--rubric",
        str(RUBRIC),
        "--out",
        str(out_dir),
        *extra,
    )
    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return result, payload


def _config_with_gate_mode(tmp_path: Path, gate_mode: str) -> Path:
    lines = [
        line
        for line in CONFIG.read_text(encoding="utf-8").splitlines()
        if not line.startswith("gate_mode:")
    ]
    path = tmp_path / "normocontrol.yaml"
    path.write_text("\n".join([*lines, f"gate_mode: {gate_mode}"]) + "\n", encoding="utf-8")
    return path


def test_run_without_flag_fails_closed_on_unverifiable(tmp_path: Path) -> None:
    result, published = _run_cli(tmp_path / "strict")

    assert result.returncode == int(ExitCode.FORMAL_FAILURE), result.stdout + result.stderr
    assert published["header"]["gate_status"] == "fail"
    assert published["header"]["gate_mode"] == "strict"
    assert published["counts"]["blocking_unverifiable"] > 0
    assert "gate: FAIL" in result.stdout
    validate_published_report(published, schema=load_report_schema())


def test_run_advisory_returns_zero_and_degraded_gate_status(tmp_path: Path) -> None:
    result, published = _run_cli(tmp_path / "advisory", "--gate-mode", "advisory")

    assert result.returncode == int(ExitCode.SUCCESS), result.stdout + result.stderr
    assert published["header"]["gate_status"] == "degraded"
    assert published["header"]["gate_mode"] == "advisory"
    assert published["counts"]["blocking_unverifiable"] > 0
    assert published["header"]["degraded"] is True
    assert "gate: DEGRADED" in result.stdout
    assert "exit_code: 0" in result.stdout
    validate_published_report(published, schema=load_report_schema())

    markdown = (tmp_path / "advisory" / "report.md").read_text(encoding="utf-8")
    assert "## NORMACTRL: DEGRADED" in markdown
    assert "- Gate mode: `advisory`" in markdown
    assert "| Blocking unverifiable |" in markdown


def test_run_advisory_still_returns_two_on_proven_failure(tmp_path: Path) -> None:
    result, published = _run_cli(
        tmp_path / "advisory-fail",
        "--gate-mode",
        "advisory",
        "--only",
        "FMT-01",
        source=FAILING_PDF,
    )

    assert result.returncode == int(ExitCode.FORMAL_FAILURE), result.stdout + result.stderr
    assert published["header"]["gate_status"] == "fail"
    assert published["header"]["gate_mode"] == "advisory"
    assert published["counts"]["formal_errors"] > 0


def test_run_explicit_strict_matches_the_no_flag_run(tmp_path: Path) -> None:
    implicit_result, implicit = _run_cli(tmp_path / "implicit")
    explicit_result, explicit = _run_cli(tmp_path / "explicit", "--gate-mode", "strict")

    assert implicit_result.returncode == explicit_result.returncode
    assert implicit["exit_code"] == explicit["exit_code"] == 2
    assert implicit["counts"] == explicit["counts"]
    assert implicit["header"]["gate_mode"] == explicit["header"]["gate_mode"] == "strict"
    assert implicit["header"]["gate_status"] == explicit["header"]["gate_status"] == "fail"


@pytest.mark.parametrize(
    ("config_mode", "cli_args", "expected_mode", "expected_code"),
    [
        ("advisory", (), "advisory", ExitCode.SUCCESS),
        ("advisory", ("--gate-mode", "strict"), "strict", ExitCode.FORMAL_FAILURE),
        ("strict", ("--gate-mode", "advisory"), "advisory", ExitCode.SUCCESS),
    ],
)
def test_cli_gate_mode_beats_configuration(
    tmp_path: Path,
    config_mode: str,
    cli_args: tuple[str, ...],
    expected_mode: str,
    expected_code: ExitCode,
) -> None:
    config = _config_with_gate_mode(tmp_path, config_mode)
    out_dir = tmp_path / f"{config_mode}-{len(cli_args)}"

    result, published = _run_cli(out_dir, *cli_args, config=config)

    assert result.returncode == int(expected_code), result.stdout + result.stderr
    assert published["header"]["gate_mode"] == expected_mode


def test_invalid_gate_mode_flag_exits_three_without_traceback(tmp_path: Path) -> None:
    result = _cli(
        "--no-llm",
        "run",
        str(UNVERIFIABLE_PDF),
        "--config",
        str(CONFIG),
        "--rubric",
        str(RUBRIC),
        "--out",
        str(tmp_path / "bad-flag"),
        "--gate-mode",
        "lenient",
    )

    assert result.returncode == int(ExitCode.CONFIG_ERROR), result.stdout + result.stderr
    assert "unknown gate mode: lenient" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_invalid_gate_mode_in_config_exits_three_without_traceback(tmp_path: Path) -> None:
    config = _config_with_gate_mode(tmp_path, "lenient")

    result = _cli(
        "--no-llm",
        "run",
        str(UNVERIFIABLE_PDF),
        "--config",
        str(config),
        "--rubric",
        str(RUBRIC),
        "--out",
        str(tmp_path / "bad-config"),
    )

    assert result.returncode == int(ExitCode.CONFIG_ERROR), result.stdout + result.stderr
    assert "gate_mode" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
