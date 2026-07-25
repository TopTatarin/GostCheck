"""Integration tests for A-01 orchestrator pipeline."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from normocontrol.cache import OutputLock, StageCache, atomic_write_json
from normocontrol.domain import ExitCode, FindingStatus, RuleLayer
from normocontrol.errors import ConfigurationError
from normocontrol.orchestrator import (
    Orchestrator,
    OrchestratorHooks,
    apply_final_severity,
    run_pipeline,
)
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.run_context import RunRequest, parse_only
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
DEMO_PASS = ROOT / "tests" / "fixtures" / "demo" / "pass"
DEMO_FAIL = ROOT / "tests" / "fixtures" / "demo" / "fail"
RUBRIC = ROOT / "rubric.yaml"
CONFIG = ROOT / "normocontrol.yaml.example"
PDF_PASS = ROOT / "tests" / "fixtures" / "pdf" / "fmt_pass.pdf"


class _SuccessBuild(LatexBuildService):
    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root, main_tex
        return LatexBuildResult(
            status=LatexBuildStatus.SUCCESS,
            returncode=0,
            log_excerpt="mock ok",
        )


class _MissingBuild(LatexBuildService):
    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root, main_tex
        return LatexBuildResult(
            status=LatexBuildStatus.TOOL_MISSING,
            returncode=127,
            log_excerpt="latexmk missing",
        )


class _FailBuild(LatexBuildService):
    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root, main_tex
        return LatexBuildResult(
            status=LatexBuildStatus.COMPILE_ERROR,
            returncode=1,
            log_excerpt="mock compile error",
        )


def _request(tmp_path: Path, source: Path, **overrides: object) -> RunRequest:
    values: dict[str, object] = {
        "source": source,
        "out_dir": tmp_path / "out",
        "config_path": CONFIG,
        "rubric_path": RUBRIC,
        "no_llm": True,
        "tool_version": "0.1.0-test",
    }
    values.update(overrides)
    return RunRequest(**values)  # type: ignore[arg-type]


def test_pass_demo_exits_zero_without_llm(tmp_path: Path) -> None:
    report = run_pipeline(
        _request(tmp_path, DEMO_PASS),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )
    assert report.exit_code is ExitCode.SUCCESS
    assert (tmp_path / "out" / "report.json").is_file()
    assert (tmp_path / "out" / "stages" / "build.json").is_file()
    assert (tmp_path / "out" / "stages" / "formal.json").is_file()
    names = [stage.name for stage in report.stages]
    assert names == ["build", "formal", "semantic", "aggregate"]


def test_fail_demo_exits_two(tmp_path: Path) -> None:
    report = run_pipeline(
        _request(tmp_path, DEMO_FAIL),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )
    assert report.exit_code is ExitCode.FORMAL_FAILURE
    assert any(
        finding.status is FindingStatus.FAIL and finding.rule_id == "STR-01"
        for stage in report.stages
        if stage.name == "formal"
        for finding in stage.findings
    )


def test_semantic_tool_error_keeps_exit_zero_after_formal_pass(tmp_path: Path) -> None:
    def boom() -> object:
        raise RuntimeError("provider down")

    report = run_pipeline(
        _request(tmp_path, DEMO_PASS, no_llm=False, provider="ollama"),
        OrchestratorHooks(build_service=_SuccessBuild(), provider_factory=boom),  # type: ignore[arg-type]
    )
    assert report.exit_code is ExitCode.SUCCESS
    semantic = next(stage for stage in report.stages if stage.name == "semantic")
    assert any(item.status is FindingStatus.UNVERIFIABLE for item in semantic.findings)
    assert all(item.layer is RuleLayer.LLM for item in semantic.findings)
    published = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert published["header"]["degraded"] is True
    assert published["counts"]["blocking_unverifiable"] == 0


def test_disabled_llm_does_not_enable_degraded_mode(tmp_path: Path) -> None:
    report = run_pipeline(
        _request(tmp_path, PDF_PASS, only=parse_only(("FMT-01",))),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )

    published = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report.exit_code is ExitCode.SUCCESS
    assert published["header"]["model_id"] is None
    assert published["header"]["degraded"] is False
    assert published["counts"]["blocking_unverifiable"] == 0


def test_cache_hit_miss_and_invalidation(tmp_path: Path) -> None:
    hooks = OrchestratorHooks(build_service=_SuccessBuild())
    first = run_pipeline(_request(tmp_path, DEMO_PASS), hooks)
    second = run_pipeline(_request(tmp_path, DEMO_PASS), hooks)
    assert first.exit_code is ExitCode.SUCCESS
    assert second.exit_code is ExitCode.SUCCESS
    build_meta = (tmp_path / "out" / "stages" / "build.json").read_text(encoding="utf-8")
    assert "hit" in build_meta or "miss" in build_meta

    cache = StageCache(tmp_path / "out" / "cache")
    cache.invalidate()
    third = run_pipeline(_request(tmp_path, DEMO_PASS), hooks)
    assert third.exit_code is ExitCode.SUCCESS


def test_cached_stages_keep_current_aggregate_timestamp(tmp_path: Path) -> None:
    first_stamp = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)
    second_stamp = datetime(2026, 7, 24, 11, 0, tzinfo=UTC)
    run_pipeline(
        _request(tmp_path, DEMO_PASS),
        OrchestratorHooks(
            build_service=_SuccessBuild(),
            report_clock=lambda: first_stamp,
        ),
    )
    run_pipeline(
        _request(tmp_path, DEMO_PASS),
        OrchestratorHooks(
            build_service=_SuccessBuild(),
            report_clock=lambda: second_stamp,
        ),
    )

    build_stage = json.loads(
        (tmp_path / "out" / "stages" / "build.json").read_text(encoding="utf-8")
    )
    published = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert build_stage["meta"]["cache"] == "hit"
    assert published["header"]["generated_at"] == "2026-07-24T11:00:00Z"


def test_corrupt_cache_is_ignored_and_rebuilt(tmp_path: Path) -> None:
    first_stamp = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)
    second_stamp = datetime(2026, 7, 24, 11, 0, tzinfo=UTC)
    request = _request(tmp_path, DEMO_PASS)
    run_pipeline(
        request,
        OrchestratorHooks(
            build_service=_SuccessBuild(),
            report_clock=lambda: first_stamp,
        ),
    )
    for cache_path in (tmp_path / "out" / "cache").rglob("*.json"):
        cache_path.write_text("{synthetic corrupt cache", encoding="utf-8")

    report = run_pipeline(
        request,
        OrchestratorHooks(
            build_service=_SuccessBuild(),
            report_clock=lambda: second_stamp,
        ),
    )

    published = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    run_state = json.loads((tmp_path / "out" / "run_state.json").read_text(encoding="utf-8"))
    assert report.exit_code is ExitCode.SUCCESS
    assert published["header"]["generated_at"] == "2026-07-24T11:00:00Z"
    assert any("corrupt" in message for message in run_state["messages"])


def test_backward_duration_clock_never_publishes_negative_duration(tmp_path: Path) -> None:
    ticks = iter(float(value) for value in range(100, 0, -1))
    report = run_pipeline(
        _request(tmp_path, DEMO_PASS),
        OrchestratorHooks(
            build_service=_SuccessBuild(),
            clock=lambda: next(ticks),
            report_clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
        ),
    )

    assert all(stage.duration_ms >= 0 for stage in report.stages)


def test_unknown_only_prefix_raises_config_error() -> None:
    with pytest.raises(ConfigurationError, match="unknown --only prefix"):
        parse_only(("not-a-stage",))


def test_parallel_lock_and_stale_lock(tmp_path: Path) -> None:
    out = tmp_path / "locked"
    with OutputLock(out), pytest.raises(Exception, match="locked"):
        OutputLock(out).acquire()
    lock_path = out / ".normocontrol.lock"
    atomic_write_json(lock_path, {"pid": 1})
    os.utime(lock_path, (0, 0))
    lock = OutputLock(out, stale_after_s=0.0)
    lock.acquire()
    lock.release()


def test_fail_closed_build_sets_internal_exit(tmp_path: Path) -> None:
    report = run_pipeline(
        _request(tmp_path, DEMO_PASS, fail_closed=True),
        OrchestratorHooks(build_service=_FailBuild()),
    )
    assert report.exit_code is ExitCode.INTERNAL_ERROR


def test_missing_latexmk_degraded_mode(tmp_path: Path) -> None:
    report = run_pipeline(
        _request(tmp_path, DEMO_PASS),
        OrchestratorHooks(build_service=_MissingBuild()),
    )
    assert report.exit_code is ExitCode.SUCCESS
    build = next(stage for stage in report.stages if stage.name == "build")
    assert any(item.status is FindingStatus.UNVERIFIABLE for item in build.findings)
    formal = next(stage for stage in report.stages if stage.name == "formal")
    assert all(item.rule_id != "SYS-03" for item in formal.findings)


def test_final_severity_applies_ann03_and_rev01() -> None:
    config = load_config(CONFIG)
    rubric = expand_rubric(load_rubric(RUBRIC), config)
    updated = apply_final_severity(rubric)
    by_id = {rule.id: rule for rule in updated.rules}
    assert by_id["ANN-03"].severity.value == "error"
    assert by_id["REV-01"].severity.value == "error"


def test_pdf_only_source_runs_degraded(tmp_path: Path) -> None:
    pdf_fixture = ROOT / "tests" / "fixtures" / "pdf"
    candidates = list(pdf_fixture.rglob("*.pdf")) if pdf_fixture.exists() else []
    if not candidates:
        pytest.skip("no pdf fixture available")
    report = run_pipeline(
        _request(tmp_path, candidates[0], only=parse_only(("build", "formal", "aggregate"))),
        OrchestratorHooks(build_service=_SuccessBuild()),
    )
    assert report.exit_code in {ExitCode.SUCCESS, ExitCode.FORMAL_FAILURE}
    assert any(stage.name == "formal" for stage in report.stages)
    published = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert published["header"]["degraded"] is True
    assert published["counts"]["blocking_unverifiable"] > 0
    assert "Blocking unverifiable" in markdown


def test_canceled_flag_writes_summary(tmp_path: Path) -> None:
    orch = Orchestrator(OrchestratorHooks(build_service=_SuccessBuild()))
    orch._canceled = True
    request = _request(tmp_path, DEMO_PASS, only=parse_only(("build",)))
    report = orch.run(request)
    canceled = json.loads((tmp_path / "out" / "canceled.json").read_text(encoding="utf-8"))
    assert canceled["canceled"] is True
    assert canceled["exit_code"] == int(report.exit_code)
