"""Tests for merge gate policy."""

from __future__ import annotations

import pytest

from normocontrol.domain import ExitCode, Finding, FindingStatus, RuleLayer, Severity
from normocontrol.rules.gate import (
    GateOutcome,
    blocks_merge,
    evaluate_gate,
    finding_blocks_merge,
    finding_is_blocking_unverifiable,
    formal_exit_code,
)


def make_finding(
    *,
    layer: RuleLayer = RuleLayer.SCRIPT,
    severity: Severity = Severity.ERROR,
    status: FindingStatus = FindingStatus.FAIL,
) -> Finding:
    return Finding(
        rule_id="SYS-01",
        layer=layer,
        severity=severity,
        status=status,
        message="test",
    )


@pytest.mark.parametrize(
    ("layer", "severity", "status", "expected"),
    [
        (RuleLayer.SCRIPT, Severity.ERROR, FindingStatus.FAIL, True),
        (RuleLayer.CLASS, Severity.ERROR, FindingStatus.FAIL, True),
        (RuleLayer.CLASS_SCRIPT, Severity.ERROR, FindingStatus.FAIL, True),
        (RuleLayer.SCRIPT, Severity.WARN, FindingStatus.FAIL, False),
        (RuleLayer.SCRIPT, Severity.ERROR, FindingStatus.WARN, False),
        (RuleLayer.SCRIPT, Severity.ERROR, FindingStatus.UNVERIFIABLE, True),
        (RuleLayer.CLASS, Severity.ERROR, FindingStatus.UNVERIFIABLE, True),
        (RuleLayer.CLASS_SCRIPT, Severity.ERROR, FindingStatus.UNVERIFIABLE, True),
        (RuleLayer.SCRIPT, Severity.WARN, FindingStatus.UNVERIFIABLE, False),
        (RuleLayer.SCRIPT, Severity.ERROR, FindingStatus.PASS, False),
        (RuleLayer.LLM, Severity.ERROR, FindingStatus.UNVERIFIABLE, False),
        (RuleLayer.VISION, Severity.ERROR, FindingStatus.UNVERIFIABLE, False),
        (RuleLayer.LLM, Severity.ERROR, FindingStatus.WARN, False),
        (RuleLayer.VISION, Severity.INFO, FindingStatus.WARN, False),
    ],
)
def test_gate_policy_matrix(
    layer: RuleLayer,
    severity: Severity,
    status: FindingStatus,
    expected: bool,
) -> None:
    finding = make_finding(layer=layer, severity=severity, status=status)
    if layer in {RuleLayer.LLM, RuleLayer.VISION} and status is FindingStatus.FAIL:
        pytest.skip("domain model forbids advisory fail status")
    assert finding_blocks_merge(finding) is expected


def test_llm_error_severity_does_not_block_merge() -> None:
    finding = Finding(
        rule_id="ANN-01",
        layer=RuleLayer.LLM,
        severity=Severity.ERROR,
        status=FindingStatus.WARN,
        message="advisory only",
    )

    assert finding_blocks_merge(finding) is False
    assert blocks_merge((finding,)) is False


def test_evaluate_gate_collects_blocking_findings() -> None:
    blocking = make_finding()
    advisory = Finding(
        rule_id="ANN-01",
        layer=RuleLayer.LLM,
        severity=Severity.WARN,
        status=FindingStatus.WARN,
        message="note",
    )

    decision = evaluate_gate((advisory, blocking))

    assert decision.outcome is GateOutcome.FAIL
    assert decision.blocking_findings == (blocking,)


def test_formal_exit_code_matches_gate() -> None:
    assert formal_exit_code((make_finding(),)) is ExitCode.FORMAL_FAILURE
    incomplete = make_finding(status=FindingStatus.UNVERIFIABLE)
    assert finding_is_blocking_unverifiable(incomplete)
    assert formal_exit_code((incomplete,)) is ExitCode.FORMAL_FAILURE
    assert formal_exit_code(()) is ExitCode.SUCCESS
