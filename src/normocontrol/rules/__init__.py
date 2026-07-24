"""Deterministic formal rule execution and merge gate policy."""

from normocontrol.rules.base import FormalRule, RuleExecutionError, RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, LatexProject, SourceKind
from normocontrol.rules.engine import (
    EngineRunResult,
    FormalEngine,
    RunMode,
    dedupe_findings,
    finding_fingerprint,
    serialize_findings,
)
from normocontrol.rules.gate import GateDecision, blocks_merge, evaluate_gate, formal_exit_code
from normocontrol.rules.registry import ImplementationStatus, RuleRegistration, RuleRegistry

__all__ = [
    "EngineRunResult",
    "ExecutionContext",
    "FormalEngine",
    "FormalRule",
    "GateDecision",
    "ImplementationStatus",
    "LatexProject",
    "RuleExecutionError",
    "RuleRegistration",
    "RuleRegistry",
    "RuleRunOutcome",
    "RunMode",
    "SourceKind",
    "blocks_merge",
    "dedupe_findings",
    "evaluate_gate",
    "finding_fingerprint",
    "formal_exit_code",
    "serialize_findings",
]
