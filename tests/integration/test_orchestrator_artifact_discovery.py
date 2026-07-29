"""End-to-end discovery of LaTeX bibliography and compiled PDF artifacts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unicodedata
from collections.abc import Callable
from pathlib import Path

import fitz
import pytest
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.domain import Finding, FindingStatus, RunReport
from normocontrol.errors import ConfigurationError
from normocontrol.extract.base import SourceFormat
from normocontrol.orchestrator import OrchestratorHooks, run_pipeline
from normocontrol.rules.context import ExecutionContext
from normocontrol.rules.engine import EngineRunResult, FormalEngine
from normocontrol.run_context import RunRequest, parse_only
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / "rubric.yaml"
CONFIG = ROOT / "normocontrol.yaml.example"
BIB_PASS = ROOT / "tests" / "fixtures" / "latex" / "bib" / "pass"
LATEX_PASS = ROOT / "tests" / "fixtures" / "latex" / "pass"


class _SuccessBuild(LatexBuildService):
    def __init__(self, writer: Callable[[Path], None] | None = None) -> None:
        self.writer = writer
        self.calls = 0

    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root
        self.calls += 1
        if self.writer is not None:
            self.writer(main_tex.with_suffix(".pdf"))
        return LatexBuildResult(
            status=LatexBuildStatus.SUCCESS,
            returncode=0,
            log_excerpt="synthetic build success",
        )


def _request(
    tmp_path: Path,
    source: Path,
    *,
    only: tuple[str, ...] = ("BIB",),
    out_name: str = "out",
) -> RunRequest:
    return RunRequest(
        source=source,
        out_dir=tmp_path / out_name,
        config_path=CONFIG,
        rubric_path=RUBRIC,
        no_llm=True,
        only=parse_only(only),
        tool_version="artifact-discovery-test",
    )


def _copy_project(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


def _capture_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> list[ExecutionContext]:
    captured: list[ExecutionContext] = []
    original = FormalEngine.run

    def capture(self: FormalEngine, context: ExecutionContext) -> EngineRunResult:
        captured.append(context)
        return original(self, context)

    monkeypatch.setattr(FormalEngine, "run", capture)
    return captured


def _write_pdf(path: Path, text: str = "Synthetic PDF body") -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((90, 100), text, fontsize=14, fontname="helv")
    document.save(path)
    document.close()


def _formal_findings(report: RunReport) -> tuple[Finding, ...]:
    formal = next(stage for stage in report.stages if stage.name == "formal")
    return formal.findings


def test_includegraphics_does_not_shadow_input_during_artifact_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics[width=\\textwidth]{figures/a.png}\n"
        "\\input{chapter}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (project / "chapter.tex").write_text("Included chapter.", encoding="utf-8")
    captured = _capture_contexts(monkeypatch)

    report = run_pipeline(
        _request(tmp_path, project),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )

    assert report.exit_code == 0
    assert len(captured) == 1
    assert captured[0].bundle is not None
    assert [source.path for source in captured[0].bundle.source_files] == [
        "main.tex",
        "chapter.tex",
    ]
    assert "Included chapter." in captured[0].bundle.text


@pytest.mark.parametrize(
    ("commands", "names"),
    [
        (r"\addbibresource{refs.bib}", ("refs.bib",)),
        (r"\bibliography{a,b.bib}", ("a.bib", "b.bib")),
        (
            "\n".join(
                (
                    r"\addbibresource{refs.bib}",
                    r"\bibliography{refs,refs.bib}",
                )
            ),
            ("refs.bib",),
        ),
    ],
)
def test_orchestrator_passes_discovered_bibliographies_to_formal_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    commands: str,
    names: tuple[str, ...],
) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    (project / "main.tex").write_text(
        f"\\documentclass{{gostcheck-vkr}}\n{commands}\n"
        "\\begin{document}\\section{Обзор НТИ}Synthetic.\\end{document}\n",
        encoding="utf-8",
    )
    (project / "refs.bib").unlink(missing_ok=True)
    for name in names:
        (project / name).write_text("", encoding="utf-8")
    captured = _capture_contexts(monkeypatch)

    run_pipeline(
        _request(tmp_path, project),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )

    assert len(captured) == 1
    assert tuple(path.name for path in captured[0].bib_paths) == names


def test_missing_bibliography_reaches_formal_engine_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    (project / "refs.bib").unlink()
    captured = _capture_contexts(monkeypatch)

    report = run_pipeline(
        _request(tmp_path, project),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )

    assert captured[0].bib_paths == ()
    findings = _formal_findings(report)
    assert any(
        finding.rule_id.startswith("BIB-")
        and finding.status is FindingStatus.UNVERIFIABLE
        and "required source unavailable: bib_files" in finding.message
        for finding in findings
    )


def test_nfd_bibliography_filename_reaches_formal_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    nfd_name = unicodedata.normalize("NFD", "Источники") + ".bib"
    (project / "refs.bib").replace(project / nfd_name)
    main = project / "main.tex"
    main.write_text(
        main.read_text(encoding="utf-8").replace("refs.bib", nfd_name),
        encoding="utf-8",
    )
    captured = _capture_contexts(monkeypatch)

    run_pipeline(
        _request(tmp_path, project),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )

    assert tuple(path.name for path in captured[0].bib_paths) == (nfd_name,)


def test_traversal_is_rejected_without_disclosing_absolute_path(tmp_path: Path) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    outside = tmp_path / "outside.bib"
    outside.write_text("@book{private, title={SECRET}}", encoding="utf-8")
    main = project / "main.tex"
    main.write_text(
        "\\documentclass{gostcheck-vkr}\n"
        "\\addbibresource{../outside.bib}\n"
        "\\begin{document}Synthetic.\\end{document}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        run_pipeline(
            _request(tmp_path, project),
            OrchestratorHooks(build_service=_SuccessBuild()),
        )

    message = str(raised.value)
    assert str(tmp_path.resolve()) not in message
    assert "SECRET" not in message


def test_directory_link_outside_project_is_rejected_by_orchestrator(tmp_path: Path) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "refs.bib").write_text("", encoding="utf-8")
    link = project / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    (project / "main.tex").write_text(
        "\\documentclass{gostcheck-vkr}\n"
        "\\addbibresource{linked/refs.bib}\n"
        "\\begin{document}Synthetic.\\end{document}\n",
        encoding="utf-8",
    )

    try:
        with pytest.raises(ConfigurationError, match="outside project root"):
            run_pipeline(
                _request(tmp_path, project),
                OrchestratorHooks(build_service=_SuccessBuild()),
            )
    finally:
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            os.rmdir(link)


def test_successful_build_passes_pdf_metrics_without_losing_latex_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _copy_project(LATEX_PASS, tmp_path / "project")
    captured = _capture_contexts(monkeypatch)

    report = run_pipeline(
        _request(tmp_path, project, only=("FMT-01",)),
        OrchestratorHooks(build_service=_SuccessBuild(_write_pdf)),
    )

    context = captured[0]
    assert context.bundle is not None
    assert context.bundle.source_format is SourceFormat.LATEX
    assert context.bundle.sections
    assert context.pdf_bundle is not None
    assert context.pdf_bundle.source_format is SourceFormat.PDF
    assert context.pdf_bundle.spans
    assert context.pdf_bundle.pages
    assert any(
        finding.rule_id == "FMT-01" and "PDF-спанов" in finding.message
        for finding in _formal_findings(report)
    )


@pytest.mark.parametrize(
    ("writer", "message"),
    [
        (None, "compiled PDF отсутствует"),
        (lambda path: path.write_bytes(b"not-a-pdf"), "PdfExtractionError"),
    ],
)
def test_successful_latexmk_with_missing_or_corrupt_pdf_is_safe_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: Callable[[Path], None] | None,
    message: str,
) -> None:
    project = _copy_project(LATEX_PASS, tmp_path / "project")
    captured = _capture_contexts(monkeypatch)

    report = run_pipeline(
        _request(tmp_path, project, only=("FMT-01",)),
        OrchestratorHooks(build_service=_SuccessBuild(writer)),
    )

    build = next(stage for stage in report.stages if stage.name == "build")
    assert any(message in finding.message for finding in build.findings)
    assert captured[0].pdf_bundle is None
    serialized = (tmp_path / "out" / "report.json").read_text(encoding="utf-8")
    assert str(project.resolve()) not in serialized


def test_bibliography_change_invalidates_build_cache(tmp_path: Path) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    build = _SuccessBuild()
    hooks = OrchestratorHooks(build_service=build)
    request = _request(tmp_path, project)

    run_pipeline(request, hooks)
    run_pipeline(request, hooks)
    (project / "refs.bib").write_text(
        (project / "refs.bib").read_text(encoding="utf-8") + "\n% changed\n",
        encoding="utf-8",
    )
    run_pipeline(request, hooks)

    assert build.calls == 2


def test_compiled_pdf_change_invalidates_build_cache(tmp_path: Path) -> None:
    project = _copy_project(LATEX_PASS, tmp_path / "project")
    compiled = project / "main.pdf"
    _write_pdf(compiled, "First synthetic PDF")
    build = _SuccessBuild()
    hooks = OrchestratorHooks(build_service=build)
    request = _request(tmp_path, project, only=("FMT-01",))

    run_pipeline(request, hooks)
    run_pipeline(request, hooks)
    compiled.unlink()
    _write_pdf(compiled, "Changed synthetic PDF")
    run_pipeline(request, hooks)

    assert build.calls == 2


def test_bibliography_decode_error_does_not_publish_path_or_contents(tmp_path: Path) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    (project / "refs.bib").write_bytes(b"\xffSYNTHETIC-BIB-MARKER")

    report = run_pipeline(
        _request(tmp_path, project, only=("BIB-03",)),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )

    finding = next(item for item in _formal_findings(report) if item.rule_id == "BIB-03")
    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "refs.bib" in finding.message
    assert str(project.resolve()) not in finding.message
    assert "SYNTHETIC-BIB-MARKER" not in finding.message
    serialized = (tmp_path / "out" / "report.json").read_text(encoding="utf-8")
    assert str(project.resolve()) not in serialized
    assert "SYNTHETIC-BIB-MARKER" not in serialized


def test_cli_runs_bib01_to_bib05_and_rev01_to_rev04_without_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _copy_project(BIB_PASS, tmp_path / "project")
    out = tmp_path / "cli-out"
    build = _SuccessBuild()

    def pipeline(request: RunRequest) -> object:
        return run_pipeline(request, OrchestratorHooks(build_service=build))

    monkeypatch.setattr(cli, "run_pipeline", pipeline)
    result = CliRunner().invoke(
        cli.app,
        [
            "--no-llm",
            "run",
            str(project),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out),
            "--only",
            "BIB",
            "--only",
            "REV",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    formal_stage = next(stage for stage in payload["stages"] if stage["name"] == "formal")
    rule_ids = {finding["rule_id"] for finding in formal_stage["findings"]}
    assert {f"BIB-{index:02d}" for index in range(1, 6)} <= rule_ids
    assert {f"REV-{index:02d}" for index in range(1, 5)} <= rule_ids
    assert all(
        "required source unavailable: bib_files" not in finding["message"]
        for finding in formal_stage["findings"]
        if finding["rule_id"].startswith(("BIB-", "REV-"))
    )
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(project.resolve()) not in serialized
