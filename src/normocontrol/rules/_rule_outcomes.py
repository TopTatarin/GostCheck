"""Small outcome builders shared by formal rule modules."""

from __future__ import annotations

from normocontrol.domain import FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome


def rule_outcome(
    rule: EffectiveRule,
    *,
    layer: RuleLayer,
    status: FindingStatus,
    message: str,
    severity: Severity | None = None,
    page: int | None = None,
) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=layer,
                status=status,
                severity=severity,
                message=message,
                page=page,
            ),
        )
    )


def combine_class_script(
    rule: EffectiveRule,
    *,
    class_ok: bool | None,
    script_ok: bool | None,
    pass_message: str,
    class_fail_message: str,
    script_fail_message: str,
    class_missing_message: str,
    script_missing_message: str,
    script_optional: bool = False,
    script_warn: bool = False,
) -> RuleRunOutcome:
    layer = RuleLayer.CLASS_SCRIPT
    if class_ok is False:
        return rule_outcome(
            rule,
            layer=layer,
            status=FindingStatus.FAIL,
            message=class_fail_message,
        )
    if script_ok is False:
        status = FindingStatus.WARN if script_warn else FindingStatus.FAIL
        return rule_outcome(rule, layer=layer, status=status, message=script_fail_message)
    if class_ok is None:
        return rule_outcome(
            rule,
            layer=layer,
            status=FindingStatus.UNVERIFIABLE,
            message=class_missing_message,
        )
    if script_ok is None:
        if script_optional:
            return rule_outcome(rule, layer=layer, status=FindingStatus.PASS, message=pass_message)
        return rule_outcome(
            rule,
            layer=layer,
            status=FindingStatus.UNVERIFIABLE,
            message=script_missing_message,
        )
    return rule_outcome(rule, layer=layer, status=FindingStatus.PASS, message=pass_message)
