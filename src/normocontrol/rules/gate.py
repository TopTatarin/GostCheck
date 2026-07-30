"""Merge gate policy for formal findings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from normocontrol.domain import (
    ExitCode,
    Finding,
    FindingStatus,
    GateMode,
    RuleLayer,
    Severity,
)


class GateOutcome(StrEnum):
    """High-level merge gate decision."""

    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Structured gate evaluation for one formal run."""

    outcome: GateOutcome
    blocking_findings: tuple[Finding, ...] = ()
    mode: GateMode = GateMode.STRICT
    suppressed_unverifiable: tuple[Finding, ...] = ()


_FORMAL_LAYERS = frozenset(
    {
        RuleLayer.CLASS,
        RuleLayer.SCRIPT,
        RuleLayer.CLASS_SCRIPT,
    }
)


def is_formal_layer(layer: RuleLayer) -> bool:
    """Return whether a finding layer participates in the hard gate."""
    return layer in _FORMAL_LAYERS


def finding_blocks_merge(finding: Finding, *, mode: GateMode = GateMode.STRICT) -> bool:
    """Apply layer x severity x status policy to one finding under ``mode``."""
    if not is_formal_layer(finding.layer):
        return False
    if finding.severity is not Severity.ERROR:
        return False
    if finding.status is FindingStatus.FAIL:
        return True
    # Advisory mode keeps proven violations blocking but stops blocking on
    # checks that could not be performed at all.
    return mode is GateMode.STRICT and finding.status is FindingStatus.UNVERIFIABLE


def finding_is_blocking_unverifiable(finding: Finding) -> bool:
    """Return whether a formal incomplete check blocks without proving a violation."""
    return (
        is_formal_layer(finding.layer)
        and finding.severity is Severity.ERROR
        and finding.status is FindingStatus.UNVERIFIABLE
    )


def evaluate_gate(
    findings: tuple[Finding, ...],
    *,
    mode: GateMode = GateMode.STRICT,
) -> GateDecision:
    """Compute gate outcome from formal findings under ``mode``."""
    blocking = tuple(finding for finding in findings if finding_blocks_merge(finding, mode=mode))
    suppressed = (
        ()
        if mode is GateMode.STRICT
        else tuple(finding for finding in findings if finding_is_blocking_unverifiable(finding))
    )
    outcome = GateOutcome.FAIL if blocking else GateOutcome.PASS
    return GateDecision(
        outcome=outcome,
        blocking_findings=blocking,
        mode=mode,
        suppressed_unverifiable=suppressed,
    )


def blocks_merge(findings: tuple[Finding, ...], *, mode: GateMode = GateMode.STRICT) -> bool:
    """Return whether merge must be blocked."""
    return evaluate_gate(findings, mode=mode).outcome is GateOutcome.FAIL


def formal_exit_code(
    findings: tuple[Finding, ...],
    *,
    mode: GateMode = GateMode.STRICT,
) -> ExitCode:
    """Map formal findings to documented CLI exit codes."""
    return ExitCode.FORMAL_FAILURE if blocks_merge(findings, mode=mode) else ExitCode.SUCCESS
