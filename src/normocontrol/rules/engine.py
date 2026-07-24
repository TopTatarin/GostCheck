"""Deterministic orchestration of formal rubric rules."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from normocontrol.domain import Finding, FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import Capability, EffectiveRule
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.base import RuleExecutionError
from normocontrol.rules.context import ExecutionContext
from normocontrol.rules.gate import GateDecision, evaluate_gate, formal_exit_code
from normocontrol.rules.registry import ImplementationStatus, RuleRegistry


class RunMode(StrEnum):
    """Execution scheduling mode."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class EngineStateError(Exception):
    """Raised when the engine cannot continue (for example canceled run)."""


@dataclass(frozen=True, slots=True)
class EngineRunResult:
    """Deterministic formal stage output."""

    findings: tuple[Finding, ...]
    gate: GateDecision
    exit_code: int


def capability_to_layer(capability: Capability) -> RuleLayer:
    """Map rubric capability tokens to public finding layers."""
    if capability is Capability.CLASS:
        return RuleLayer.CLASS
    if capability is Capability.SCRIPT:
        return RuleLayer.SCRIPT
    if capability is Capability.LLM:
        return RuleLayer.LLM
    return RuleLayer.VISION


def primary_formal_layer(rule: EffectiveRule) -> RuleLayer:
    """Choose the layer recorded on formal findings for one rubric rule."""
    caps = set(rule.capabilities)
    if Capability.CLASS in caps and Capability.SCRIPT in caps:
        return RuleLayer.CLASS_SCRIPT
    if Capability.CLASS in caps:
        return RuleLayer.CLASS
    if Capability.SCRIPT in caps:
        return RuleLayer.SCRIPT
    return capability_to_layer(rule.capabilities[0])


def finding_fingerprint(finding: Finding) -> str:
    """Stable SHA-256 fingerprint for reproducible comparisons."""
    payload = finding.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def serialize_findings(findings: tuple[Finding, ...]) -> list[dict[str, Any]]:
    """Serialize findings with fingerprints for golden comparisons."""
    return [
        {
            "finding": finding.model_dump(mode="json", exclude_none=True),
            "fingerprint": finding_fingerprint(finding),
        }
        for finding in findings
    ]


def _sort_key(finding: Finding, rubric_index: dict[str, int]) -> tuple[int, str, str]:
    locator = finding.evidence[0].locator if finding.evidence else ""
    return (rubric_index.get(finding.rule_id, 10_000), locator, finding_fingerprint(finding))


class FormalEngine:
    """Runs applicable class/script rules and computes the formal gate."""

    def __init__(self, registry: RuleRegistry) -> None:
        self._registry = registry

    def run(
        self,
        context: ExecutionContext,
        *,
        mode: RunMode = RunMode.SEQUENTIAL,
        rule_timeout_s: float | None = None,
    ) -> EngineRunResult:
        """Execute enabled formal rules in rubric order."""
        del rule_timeout_s  # reserved for subprocess rules in later tasks
        if context.canceled:
            raise EngineStateError("run canceled")

        rubric_index = {rule.id: index for index, rule in enumerate(context.rubric.rules)}
        formal_rules = [
            rule
            for rule in context.rubric.rules
            if rule.enabled and _rule_has_formal_capability(rule)
        ]

        if mode is RunMode.SEQUENTIAL:
            raw_findings = [
                finding
                for rule in formal_rules
                for finding in self._evaluate_rule(context, rule, rubric_index)
            ]
        else:
            raw_findings = self._run_parallel(context, formal_rules, rubric_index)

        findings = self._sort_findings(tuple(raw_findings), rubric_index)
        gate = evaluate_gate(findings)
        return EngineRunResult(
            findings=findings,
            gate=gate,
            exit_code=int(formal_exit_code(findings)),
        )

    def _run_parallel(
        self,
        context: ExecutionContext,
        formal_rules: list[EffectiveRule],
        rubric_index: dict[str, int],
    ) -> list[Finding]:
        collected: list[Finding] = []
        with ThreadPoolExecutor(max_workers=max(1, len(formal_rules))) as pool:
            futures = {
                pool.submit(self._evaluate_rule, context, rule, rubric_index): rule
                for rule in formal_rules
            }
            for future in as_completed(futures):
                collected.extend(future.result())
        return collected

    def _evaluate_rule(
        self,
        context: ExecutionContext,
        rule: EffectiveRule,
        rubric_index: dict[str, int],
    ) -> tuple[Finding, ...]:
        del rubric_index
        layer = primary_formal_layer(rule)
        registration = self._registry.get(rule.id)

        if registration is None:
            return (
                _make_finding(
                    rule,
                    layer=layer,
                    status=FindingStatus.UNVERIFIABLE,
                    severity=rule.severity,
                    message="implementation missing for formal rule",
                ),
            )

        if registration.status is ImplementationStatus.UNSUPPORTED:
            return (
                _make_finding(
                    rule,
                    layer=layer,
                    status=FindingStatus.UNVERIFIABLE,
                    severity=rule.severity,
                    message=f"unsupported: {registration.reason}",
                ),
            )

        implementation = registration.implementation
        assert implementation is not None

        missing = context.missing_sources(implementation.required_sources)
        if missing:
            missing_names = ", ".join(item.value for item in missing)
            return (
                _make_finding(
                    rule,
                    layer=layer,
                    status=FindingStatus.UNVERIFIABLE,
                    severity=rule.severity,
                    message=f"required source unavailable: {missing_names}",
                ),
            )

        if not implementation.supports(context, rule):
            return (
                _make_finding(
                    rule,
                    layer=layer,
                    status=FindingStatus.NOT_APPLICABLE,
                    severity=rule.severity,
                    message="rule not applicable to current inputs",
                ),
            )

        try:
            outcome = implementation.run(context, rule)
        except RuleExecutionError as error:
            return (_tool_error_finding(rule, layer, str(error), context.fail_closed),)
        except Exception as error:
            return (_tool_error_finding(rule, layer, str(error), context.fail_closed),)

        return outcome.findings

    @staticmethod
    def _sort_findings(
        findings: tuple[Finding, ...],
        rubric_index: dict[str, int],
    ) -> tuple[Finding, ...]:
        return tuple(sorted(findings, key=lambda item: _sort_key(item, rubric_index)))


def _rule_has_formal_capability(rule: EffectiveRule) -> bool:
    return any(
        capability in {Capability.CLASS, Capability.SCRIPT} for capability in rule.capabilities
    )


def _domain_severity(severity: RubricSeverity | Severity) -> Severity:
    """Map rubric severities onto public domain severities."""
    return Severity(severity.value)


def _make_finding(
    rule: EffectiveRule,
    *,
    layer: RuleLayer,
    status: FindingStatus,
    severity: RubricSeverity | Severity,
    message: str,
    evidence_locator: str | None = None,
) -> Finding:
    from normocontrol.domain import Evidence

    evidence: tuple[Evidence, ...] = ()
    if evidence_locator is not None:
        evidence = (Evidence(locator=evidence_locator),)
    return Finding(
        rule_id=rule.id,
        layer=layer,
        severity=_domain_severity(severity),
        status=status,
        message=message,
        evidence=evidence,
    )


def _tool_error_finding(
    rule: EffectiveRule,
    layer: RuleLayer,
    detail: str,
    fail_closed: bool,
) -> Finding:
    message = f"tool_error: {detail}"
    if fail_closed:
        return _make_finding(
            rule,
            layer=layer,
            status=FindingStatus.FAIL,
            severity=Severity.ERROR,
            message=message,
        )
    return _make_finding(
        rule,
        layer=layer,
        status=FindingStatus.UNVERIFIABLE,
        severity=Severity.WARN,
        message=message,
    )


def dedupe_findings(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Collapse identical fingerprints while preserving first occurrence order."""
    seen: set[str] = set()
    unique: list[Finding] = []
    for finding in findings:
        fingerprint = finding_fingerprint(finding)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(finding)
    return tuple(unique)
