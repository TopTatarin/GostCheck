"""Unit tests for ``gate_mode`` in the published report header and gate status."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from normocontrol.domain import (
    Evidence,
    ExitCode,
    Finding,
    FindingStatus,
    GateMode,
    RuleLayer,
    RunReport,
    Severity,
    StageResult,
)
from normocontrol.reporting.json_report import (
    ReportMeta,
    build_published_report,
    gate_status_for,
    load_report_schema,
    validate_published_report,
)
from normocontrol.reporting.markdown import render_markdown, render_summary

ROOT = Path(__file__).resolve().parents[3]
BOTH_MODES = (GateMode.STRICT, GateMode.ADVISORY)


def _finding(**overrides: object) -> Finding:
    values: dict[str, object] = {
        "rule_id": "FMT-01",
        "layer": RuleLayer.CLASS,
        "severity": Severity.ERROR,
        "status": FindingStatus.UNVERIFIABLE,
        "message": "protected-files.yaml отсутствует",
        "evidence": (Evidence(locator="main.tex:1"),),
        "path": "main.tex",
    }
    values.update(overrides)
    return Finding.model_validate(values)


def _report(
    *findings: Finding,
    exit_code: ExitCode,
    gate_mode: GateMode = GateMode.STRICT,
) -> RunReport:
    return RunReport(
        tool_version="0.1.0",
        exit_code=exit_code,
        gate_mode=gate_mode,
        stages=(StageResult(name="formal", findings=findings),),
    )


def _published(report: RunReport, mode: GateMode) -> dict[str, Any]:
    return build_published_report(
        report,
        ReportMeta(commit_sha="abc1234", profile="software", repo_root=ROOT, gate_mode=mode),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )


def test_gate_status_advisory_without_findings_is_pass() -> None:
    report = _report(exit_code=ExitCode.SUCCESS, gate_mode=GateMode.ADVISORY)

    assert gate_status_for(report, mode=GateMode.ADVISORY) == "pass"


def test_gate_status_advisory_with_suppressed_unverifiable_is_degraded() -> None:
    report = _report(_finding(), exit_code=ExitCode.SUCCESS, gate_mode=GateMode.ADVISORY)

    assert gate_status_for(report, mode=GateMode.ADVISORY) == "degraded"


def test_gate_status_advisory_with_proven_failure_is_fail() -> None:
    report = _report(
        _finding(status=FindingStatus.FAIL),
        exit_code=ExitCode.FORMAL_FAILURE,
        gate_mode=GateMode.ADVISORY,
    )

    assert gate_status_for(report, mode=GateMode.ADVISORY) == "fail"


def test_gate_status_strict_with_unverifiable_is_fail() -> None:
    report = _report(_finding(), exit_code=ExitCode.FORMAL_FAILURE)

    assert gate_status_for(report) == "fail"
    assert gate_status_for(report, mode=GateMode.STRICT) == "fail"


@pytest.mark.parametrize("mode", BOTH_MODES)
@pytest.mark.parametrize("exit_code", [ExitCode.CONFIG_ERROR, ExitCode.INTERNAL_ERROR])
def test_gate_status_error_branch_is_mode_independent(
    mode: GateMode,
    exit_code: ExitCode,
) -> None:
    report = _report(exit_code=exit_code, gate_mode=mode)

    assert gate_status_for(report, mode=mode) == "error"


def test_default_gate_status_for_mode_is_strict() -> None:
    report = _report(_finding(), exit_code=ExitCode.FORMAL_FAILURE)

    assert gate_status_for(report) == gate_status_for(report, mode=GateMode.STRICT)


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_header_always_records_the_applied_gate_mode(mode: GateMode) -> None:
    exit_code = ExitCode.SUCCESS if mode is GateMode.ADVISORY else ExitCode.FORMAL_FAILURE
    published = _published(_report(_finding(), exit_code=exit_code, gate_mode=mode), mode)

    assert published["header"]["gate_mode"] == mode.value
    validate_published_report(published, schema=load_report_schema())


def test_advisory_keeps_counts_findings_and_flags_identical_to_strict() -> None:
    findings = (
        _finding(),
        _finding(rule_id="TAB-01", layer=RuleLayer.CLASS_SCRIPT),
        _finding(
            rule_id="ANN-03",
            layer=RuleLayer.LLM,
            severity=Severity.WARN,
            status=FindingStatus.WARN,
            message="APPROVAL_REQUIRED: параметр не утверждён",
        ),
    )
    strict = _published(
        _report(*findings, exit_code=ExitCode.FORMAL_FAILURE),
        GateMode.STRICT,
    )
    advisory = _published(
        _report(*findings, exit_code=ExitCode.SUCCESS, gate_mode=GateMode.ADVISORY),
        GateMode.ADVISORY,
    )

    assert advisory["counts"] == strict["counts"]
    assert advisory["counts"]["blocking_unverifiable"] == 2
    assert [item["rule_id"] for item in advisory["findings"]] == [
        item["rule_id"] for item in strict["findings"]
    ]
    assert advisory["header"]["degraded"] is True
    assert advisory["header"]["degraded"] == strict["header"]["degraded"]
    assert advisory["header"]["approvals_required"] is True
    assert advisory["header"]["approvals_required"] == strict["header"]["approvals_required"]
    assert strict["header"]["gate_status"] == "fail"
    assert advisory["header"]["gate_status"] == "degraded"
    assert advisory["exit_code"] == 0


def test_markdown_reports_gate_mode_and_degraded_status() -> None:
    published = _published(
        _report(_finding(), exit_code=ExitCode.SUCCESS, gate_mode=GateMode.ADVISORY),
        GateMode.ADVISORY,
    )

    markdown = render_markdown(published)

    assert "## NORMACTRL: DEGRADED" in markdown
    assert "- Gate mode: `advisory`" in markdown
    assert "| Blocking unverifiable | 1 |" in markdown


def test_truncated_summary_keeps_gate_mode_and_blocking_unverifiable() -> None:
    published = _published(
        _report(_finding(), exit_code=ExitCode.SUCCESS, gate_mode=GateMode.ADVISORY),
        GateMode.ADVISORY,
    )

    summary = render_summary(published, max_chars=600)

    assert "Blocking unverifiable" in summary
    assert "mode `advisory`" in summary
    assert "DEGRADED" in summary
