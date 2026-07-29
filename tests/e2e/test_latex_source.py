"""E2E coverage for LaTeX source dependency discovery."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.domain import ExitCode
from normocontrol.orchestrator import OrchestratorHooks, run_pipeline
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / "rubric.yaml"
CONFIG = ROOT / "normocontrol.yaml.example"


class _SuccessBuild(LatexBuildService):
    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root, main_tex
        return LatexBuildResult(
            status=LatexBuildStatus.SUCCESS,
            returncode=0,
            log_excerpt="mock ok",
        )


def test_run_latex_with_includegraphics_and_input_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_pipeline(request, hooks=None):  # type: ignore[no-untyped-def]
        del hooks
        return run_pipeline(request, OrchestratorHooks(build_service=_SuccessBuild()))

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
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
    out = tmp_path / "out"

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
        ],
    )

    assert result.exit_code == int(ExitCode.SUCCESS), result.stdout + result.stderr
    assert "textwidth]" not in result.stdout + result.stderr
    assert (out / "report.json").is_file()
