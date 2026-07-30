"""Tests for merge gate policy."""

from __future__ import annotations

import pytest

from normocontrol.domain import (
    ExitCode,
    Finding,
    FindingStatus,
    GateMode,
    RuleLayer,
    Severity,
)
from normocontrol.rules.gate import (
    GateOutcome,
    blocks_merge,
    evaluate_gate,
    finding_blocks_merge,
    finding_is_blocking_unverifiable,
    formal_exit_code,
    is_formal_layer,
)

BOTH_MODES = (GateMode.STRICT, GateMode.ADVISORY)


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


def test_strict_regression_blocking_unverifiable_still_blocks() -> None:
    """Regression: strict mode must keep blocking formal ERROR/UNVERIFIABLE."""
    incomplete = make_finding(layer=RuleLayer.CLASS, status=FindingStatus.UNVERIFIABLE)

    assert finding_blocks_merge(incomplete) is True
    assert blocks_merge((incomplete,)) is True
    assert evaluate_gate((incomplete,)).outcome is GateOutcome.FAIL
    assert formal_exit_code((incomplete,)) is ExitCode.FORMAL_FAILURE


def test_default_gate_mode_is_strict() -> None:
    """No caller may get advisory behaviour without asking for it."""
    incomplete = make_finding(status=FindingStatus.UNVERIFIABLE)

    assert evaluate_gate((incomplete,)).mode is GateMode.STRICT
    assert finding_blocks_merge(incomplete) is finding_blocks_merge(
        incomplete, mode=GateMode.STRICT
    )
    assert blocks_merge((incomplete,)) is blocks_merge((incomplete,), mode=GateMode.STRICT)
    assert formal_exit_code((incomplete,)) is formal_exit_code((incomplete,), mode=GateMode.STRICT)


@pytest.mark.parametrize("mode", BOTH_MODES)
@pytest.mark.parametrize("layer", [RuleLayer.CLASS, RuleLayer.SCRIPT, RuleLayer.CLASS_SCRIPT])
def test_proven_formal_failure_blocks_in_every_mode(mode: GateMode, layer: RuleLayer) -> None:
    finding = make_finding(layer=layer, status=FindingStatus.FAIL)

    assert finding_blocks_merge(finding, mode=mode) is True
    assert blocks_merge((finding,), mode=mode) is True
    assert evaluate_gate((finding,), mode=mode).outcome is GateOutcome.FAIL
    assert formal_exit_code((finding,), mode=mode) is ExitCode.FORMAL_FAILURE


@pytest.mark.parametrize("layer", [RuleLayer.CLASS, RuleLayer.SCRIPT, RuleLayer.CLASS_SCRIPT])
def test_strict_blocks_formal_unverifiable(layer: RuleLayer) -> None:
    finding = make_finding(layer=layer, status=FindingStatus.UNVERIFIABLE)

    assert finding_blocks_merge(finding, mode=GateMode.STRICT) is True
    assert blocks_merge((finding,), mode=GateMode.STRICT) is True
    assert evaluate_gate((finding,), mode=GateMode.STRICT).suppressed_unverifiable == ()


@pytest.mark.parametrize("layer", [RuleLayer.CLASS, RuleLayer.SCRIPT, RuleLayer.CLASS_SCRIPT])
def test_advisory_does_not_block_formal_unverifiable(layer: RuleLayer) -> None:
    finding = make_finding(layer=layer, status=FindingStatus.UNVERIFIABLE)

    decision = evaluate_gate((finding,), mode=GateMode.ADVISORY)

    assert finding_blocks_merge(finding, mode=GateMode.ADVISORY) is False
    assert blocks_merge((finding,), mode=GateMode.ADVISORY) is False
    assert decision.outcome is GateOutcome.PASS
    assert decision.blocking_findings == ()
    assert decision.suppressed_unverifiable == (finding,)
    assert decision.mode is GateMode.ADVISORY


def test_advisory_mixed_fail_and_unverifiable_blocks_because_of_fail() -> None:
    proven = make_finding()
    incomplete = make_finding(layer=RuleLayer.CLASS, status=FindingStatus.UNVERIFIABLE)

    decision = evaluate_gate((incomplete, proven), mode=GateMode.ADVISORY)

    assert decision.outcome is GateOutcome.FAIL
    assert decision.blocking_findings == (proven,)
    assert decision.suppressed_unverifiable == (incomplete,)
    assert formal_exit_code((incomplete, proven), mode=GateMode.ADVISORY) is (
        ExitCode.FORMAL_FAILURE
    )


@pytest.mark.parametrize("mode", BOTH_MODES)
@pytest.mark.parametrize(
    "status",
    [
        FindingStatus.PASS,
        FindingStatus.WARN,
        FindingStatus.INFO,
        FindingStatus.SKIPPED,
        FindingStatus.NOT_APPLICABLE,
        FindingStatus.FAIL,
        FindingStatus.UNVERIFIABLE,
    ],
)
def test_warn_severity_never_blocks_in_any_mode(mode: GateMode, status: FindingStatus) -> None:
    finding = make_finding(severity=Severity.WARN, status=status)

    assert finding_blocks_merge(finding, mode=mode) is False
    assert blocks_merge((finding,), mode=mode) is False


@pytest.mark.parametrize("mode", BOTH_MODES)
@pytest.mark.parametrize(
    "status",
    [
        FindingStatus.PASS,
        FindingStatus.WARN,
        FindingStatus.INFO,
        FindingStatus.SKIPPED,
        FindingStatus.NOT_APPLICABLE,
    ],
)
def test_non_failing_statuses_never_block_in_any_mode(
    mode: GateMode,
    status: FindingStatus,
) -> None:
    finding = make_finding(status=status)

    assert finding_blocks_merge(finding, mode=mode) is False
    assert blocks_merge((finding,), mode=mode) is False
    assert formal_exit_code((finding,), mode=mode) is ExitCode.SUCCESS


@pytest.mark.parametrize("mode", BOTH_MODES)
@pytest.mark.parametrize("layer", [RuleLayer.LLM, RuleLayer.VISION])
def test_semantic_and_vision_never_block_in_any_mode(mode: GateMode, layer: RuleLayer) -> None:
    # The domain model forbids status=fail on advisory layers, so warn/unverifiable
    # are the strongest advisory outcomes reachable here.
    for status in (FindingStatus.WARN, FindingStatus.UNVERIFIABLE):
        finding = Finding(
            rule_id="ANN-01",
            layer=layer,
            severity=Severity.ERROR,
            status=status,
            message="advisory only",
        )
        assert is_formal_layer(finding.layer) is False
        assert finding_blocks_merge(finding, mode=mode) is False
        assert blocks_merge((finding,), mode=mode) is False
        assert formal_exit_code((finding,), mode=mode) is ExitCode.SUCCESS


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_non_formal_layer_fail_never_blocks(mode: GateMode) -> None:
    # The layer guard runs before severity/status; ``model_construct`` bypasses the
    # domain validator that otherwise rejects fail on llm/vision.
    finding = Finding.model_construct(
        rule_id="ANN-01",
        layer=RuleLayer.LLM,
        severity=Severity.ERROR,
        status=FindingStatus.FAIL,
        message="advisory layer cannot block",
    )

    assert is_formal_layer(finding.layer) is False
    assert finding_blocks_merge(finding, mode=mode) is False
    assert blocks_merge((finding,), mode=mode) is False


@pytest.mark.parametrize(
    "status",
    [
        FindingStatus.UNVERIFIABLE,
        FindingStatus.FAIL,
        FindingStatus.WARN,
        FindingStatus.PASS,
    ],
)
def test_blocking_unverifiable_counter_is_mode_independent(status: FindingStatus) -> None:
    """The counter feeds ``counts``/``degraded`` and must never depend on the mode."""
    finding = make_finding(status=status)
    expected = status is FindingStatus.UNVERIFIABLE

    assert finding_is_blocking_unverifiable(finding) is expected
    for mode in BOTH_MODES:
        evaluate_gate((finding,), mode=mode)
        assert finding_is_blocking_unverifiable(finding) is expected


def test_formal_exit_code_per_mode() -> None:
    incomplete = make_finding(status=FindingStatus.UNVERIFIABLE)
    proven = make_finding(status=FindingStatus.FAIL)

    assert formal_exit_code((incomplete,), mode=GateMode.STRICT) is ExitCode.FORMAL_FAILURE
    assert formal_exit_code((incomplete,), mode=GateMode.ADVISORY) is ExitCode.SUCCESS
    assert formal_exit_code((proven,), mode=GateMode.ADVISORY) is ExitCode.FORMAL_FAILURE


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_empty_findings_pass_in_any_mode(mode: GateMode) -> None:
    decision = evaluate_gate((), mode=mode)

    assert decision.outcome is GateOutcome.PASS
    assert decision.blocking_findings == ()
    assert decision.suppressed_unverifiable == ()
    assert blocks_merge((), mode=mode) is False
    assert formal_exit_code((), mode=mode) is ExitCode.SUCCESS
