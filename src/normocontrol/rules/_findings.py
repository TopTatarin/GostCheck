"""Shared finding builders for formal rules."""

from __future__ import annotations

from normocontrol.domain import Evidence, Finding, FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rubric.models import Severity as RubricSeverity


def make_rule_finding(
    rule: EffectiveRule,
    *,
    layer: RuleLayer,
    status: FindingStatus,
    severity: RubricSeverity | Severity | None = None,
    message: str,
    path: str | None = None,
    page: int | None = None,
    evidence_locator: str | None = None,
) -> Finding:
    chosen = Severity((severity or rule.severity).value)
    evidence: tuple[Evidence, ...] = ()
    if evidence_locator is not None:
        evidence = (Evidence(locator=evidence_locator),)
    return Finding(
        rule_id=rule.id,
        layer=layer,
        severity=chosen,
        status=status,
        message=message,
        evidence=evidence,
        path=path,
        page=page,
    )
