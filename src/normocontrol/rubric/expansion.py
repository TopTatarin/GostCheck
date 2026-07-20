"""Safe placeholder and layer expansion for validated rubrics."""

from __future__ import annotations

import re
from collections.abc import Mapping

from normocontrol.errors import RubricValidationError
from normocontrol.rubric.models import (
    Capability,
    EffectiveRubric,
    EffectiveRule,
    NormocontrolConfig,
    ParameterName,
    Rubric,
    ValidationWarning,
)
from normocontrol.rubric.profiles import rule_enabled

_PLACEHOLDER = re.compile(r"(?<![\\A-Za-z0-9_])\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ALLOWED_LAYERS: dict[str, tuple[Capability, ...]] = {
    "class": (Capability.CLASS,),
    "script": (Capability.SCRIPT,),
    "class+script": (Capability.CLASS, Capability.SCRIPT),
    "llm": (Capability.LLM,),
    "vision": (Capability.VISION,),
    "script+llm": (Capability.SCRIPT, Capability.LLM),
}


def normalize_layer(layer: str, *, yaml_path: str = "$.layer") -> tuple[Capability, ...]:
    """Normalize supported source layer spellings while retaining the input elsewhere."""
    capabilities = _ALLOWED_LAYERS.get(layer)
    if capabilities is None:
        tokens = [token for token in layer.split("+") if token]
        unknown = sorted(set(tokens) - {item.value for item in Capability})
        detail = f"unknown layer token(s): {', '.join(unknown)}" if unknown else "invalid layer"
        raise RubricValidationError(detail, source="rubric.yaml", yaml_path=yaml_path)
    return capabilities


def _placeholders(text: str) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _PLACEHOLDER.finditer(text))


def _replace_approved(
    text: str,
    values: Mapping[str, object],
    approved: frozenset[str],
    *,
    yaml_path: str,
) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise RubricValidationError(
                f"unknown placeholder {{{name}}}", source="rubric.yaml", yaml_path=yaml_path
            )
        return str(values[name]) if name in approved else match.group(0)

    return _PLACEHOLDER.sub(replace, text)


def expand_rubric(rubric: Rubric, config: NormocontrolConfig) -> EffectiveRubric:
    """Build an immutable effective rubric from explicit, approved configuration."""
    defaults = rubric.meta.params_to_approve.model_dump()
    overrides = config.params.model_dump(exclude_none=True)
    values = defaults | overrides
    approved = frozenset(item.value for item in config.approved_params)
    used: set[str] = set()
    warnings: list[ValidationWarning] = []
    effective_rules: list[EffectiveRule] = []

    for index, rule in enumerate(rubric.rules):
        rule_path = f"$.rules[{index}]"
        found = set(_placeholders(rule.rule)) | set(_placeholders(rule.check))
        unknown = found - set(values)
        if unknown:
            name = sorted(unknown)[0]
            raise RubricValidationError(
                f"unknown placeholder {{{name}}}", source="rubric.yaml", yaml_path=rule_path
            )
        used.update(found)
        effective_rules.append(
            EffectiveRule(
                id=rule.id,
                src=rule.src,
                rule=_replace_approved(rule.rule, values, approved, yaml_path=f"{rule_path}.rule"),
                layer=rule.layer,
                capabilities=normalize_layer(rule.layer, yaml_path=f"{rule_path}.layer"),
                check=_replace_approved(
                    rule.check, values, approved, yaml_path=f"{rule_path}.check"
                ),
                severity=rule.severity,
                severity_final=rule.severity_final,
                enabled=rule_enabled(rule, config.work_profile),
            )
        )

    unused = set(values) - used
    if unused:
        names = ", ".join(sorted(unused))
        raise RubricValidationError(
            f"params_to_approve contains unused parameter(s): {names}",
            source="rubric.yaml",
            yaml_path="$.meta.params_to_approve",
        )

    if "draft" in rubric.meta.version.casefold():
        for name in ParameterName:
            if name.value not in approved:
                warnings.append(
                    ValidationWarning(
                        code="APPROVAL_REQUIRED",
                        message=f"draft parameter {name.value} is not approved",
                        yaml_path=f"$.meta.params_to_approve.{name.value}",
                    )
                )

    return EffectiveRubric(
        meta=rubric.meta,
        work_profile=config.work_profile,
        rules=tuple(effective_rules),
        warnings=tuple(warnings),
    )
