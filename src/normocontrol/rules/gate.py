"""Merge gate policy for formal findings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from normocontrol.domain import ExitCode, Finding, FindingStatus, RuleLayer, Severity


class GateOutcome(StrEnum):
    """High-level merge gate decision."""

    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Structured gate evaluation for one formal run."""

    outcome: GateOutcome
    blocking_findings: tuple[Finding, ...] = ()


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


def finding_blocks_merge(finding: Finding) -> bool:
    """Apply layer x severity x status policy to one finding."""
    if not is_formal_layer(finding.layer):
        return False
    if finding.severity is not Severity.ERROR:
        return False
    return finding.status is FindingStatus.FAIL


def evaluate_gate(findings: tuple[Finding, ...]) -> GateDecision:
    """Compute gate outcome from formal findings."""
    blocking = tuple(finding for finding in findings if finding_blocks_merge(finding))
    outcome = GateOutcome.FAIL if blocking else GateOutcome.PASS
    return GateDecision(outcome=outcome, blocking_findings=blocking)


def blocks_merge(findings: tuple[Finding, ...]) -> bool:
    """Return whether merge must be blocked."""
    return evaluate_gate(findings).outcome is GateOutcome.FAIL


def formal_exit_code(findings: tuple[Finding, ...]) -> ExitCode:
    """Map formal findings to documented CLI exit codes."""
    return ExitCode.FORMAL_FAILURE if blocks_merge(findings) else ExitCode.SUCCESS
