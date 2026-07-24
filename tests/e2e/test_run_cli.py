"""E2E CLI tests for A-01 ``normocontrol run``."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_run_help_lists_options() -> None:
    result = runner.invoke(cli.app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--out" in result.stdout
    assert "--only" in result.stdout
    assert "--final" in result.stdout


def test_run_pass_demo_exit_zero(tmp_path: Path) -> None:
    out = tmp_path / "pass"
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
    assert result.exit_code == int(ExitCode.SUCCESS), result.stdout + result.stderr
    published = json.loads((out / "report.json").read_text(encoding="utf-8"))
    validate_published_report(published, schema=load_report_schema())
    assert published["exit_code"] == 0
    assert published["header"]["gate_status"] == "pass"
    assert (out / "report.md").is_file()
    assert (out / "summary.json").is_file()


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
