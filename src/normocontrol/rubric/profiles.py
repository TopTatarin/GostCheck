"""Deterministic work profiles; no LLM output can select one."""

from __future__ import annotations

from normocontrol.rubric.models import RubricRule, ValidationWarning, WorkProfile

_DISABLED_PREFIXES: dict[WorkProfile, frozenset[str]] = {
    WorkProfile.SOFTWARE: frozenset(),
    WorkProfile.RESEARCH: frozenset({"ARC", "ALG", "IMP"}),
    WorkProfile.ORGANIZATIONAL: frozenset({"ARC", "MTH", "ALG", "IMP"}),
}


def rule_enabled(rule: RubricRule, profile: WorkProfile) -> bool:
    """Return profile applicability without guessing the profile."""
    prefix = rule.id.partition("-")[0]
    return prefix not in _DISABLED_PREFIXES[profile]


def profile_mismatch_warning(
    selected: WorkProfile,
    suggested: WorkProfile,
) -> ValidationWarning | None:
    """Convert an advisory profile suggestion into a warning, never a selection."""
    if selected is suggested:
        return None
    return ValidationWarning(
        code="PROFILE_MISMATCH",
        message=f"advisory profile {suggested.value} differs from selected {selected.value}",
        yaml_path="$.work_profile",
    )
