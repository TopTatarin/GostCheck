"""Protocols and shared types for deterministic formal rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from normocontrol.domain import Finding
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules.context import ExecutionContext, SourceKind


class RuleExecutionError(Exception):
    """Expected failure raised by a rule implementation."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RuleRunOutcome:
    """Normalized result of one formal rule invocation."""

    findings: tuple[Finding, ...] = ()


@runtime_checkable
class FormalRule(Protocol):
    """One deterministic rubric rule backed by class/script logic."""

    rule_id: str
    required_sources: frozenset[SourceKind]

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        """Return whether the rule applies to the current inputs and profile."""

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        """Evaluate the rule and return zero or more findings."""
