"""Static checks for the Normocontrol GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.orchestrator import OrchestratorHooks, run_pipeline
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "normocontrol.yml"
REQUIRED_JOBS = ("lint-and-unit", "formal-gate")


def test_workflow_yaml_parses_and_required_job_names() -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert payload["name"] == "Normocontrol"
    jobs = payload["jobs"]
    assert set(REQUIRED_JOBS).issubset(jobs)
    assert jobs["lint-and-unit"]["name"] == "lint-and-unit"
    assert jobs["formal-gate"]["name"] == "formal-gate"
    assert jobs["publish-report"]["name"] == "publish-report"
    assert jobs["build-latex"]["name"] == "build-latex"
    assert "semantic" not in jobs
    assert "semantic-advisory" not in jobs


def test_workflow_permissions_and_triggers() -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML 1.1 parses bare key `on` as boolean True.
    triggers = payload.get("on", payload.get(True))
    assert triggers is not None
    assert "pull_request" in triggers
    assert "workflow_dispatch" in triggers
    assert "pull_request_target" not in triggers
    assert payload["permissions"] == {"contents": "read"}
    publish_perms = payload["jobs"]["publish-report"]["permissions"]
    assert publish_perms["pull-requests"] == "write"
    assert publish_perms["contents"] == "read"


def test_formal_gate_uploads_artifact_always() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "if: always()" in text
    assert "actions/upload-artifact@" in text
    assert "normocontrol-report-${{ github.sha }}" in text


def test_local_formal_exit_two_leaves_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate the formal-gate fail path: exit 2 still produces report files."""

    class _SuccessBuild(LatexBuildService):
        def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
            del project_root, main_tex
            return LatexBuildResult(
                status=LatexBuildStatus.SUCCESS,
                returncode=0,
                log_excerpt="mock",
            )

    def fake_pipeline(request, hooks=None):  # type: ignore[no-untyped-def]
        del hooks
        return run_pipeline(request, OrchestratorHooks(build_service=_SuccessBuild()))

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    out = tmp_path / "fail"
    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            str(ROOT / "tests" / "fixtures" / "demo" / "fail"),
            "--no-llm",
            "--config",
            str(ROOT / "normocontrol.yaml.example"),
            "--rubric",
            str(ROOT / "rubric.yaml"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 2
    assert (out / "report.json").is_file()
    assert (out / "report.md").is_file()
    assert (out / "summary.json").is_file()
