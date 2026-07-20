"""Strict public models for rubric loading and profile expansion."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RuleId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}-[0-9]{2}$")]


class StrictModel(BaseModel):
    """Immutable model that rejects accidental YAML keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkProfile(StrEnum):
    """Profile selected explicitly by the user."""

    SOFTWARE = "software"
    RESEARCH = "research"
    ORGANIZATIONAL = "organizational"


class Severity(StrEnum):
    """Rubric severity."""

    ERROR = "error"
    WARN = "warn"
    INFO = "info"


class Capability(StrEnum):
    """One executable capability contained in a rubric layer."""

    CLASS = "class"
    SCRIPT = "script"
    LLM = "llm"
    VISION = "vision"


class ParameterName(StrEnum):
    """The only placeholders supported by the version-1 rubric."""

    FONT_SIZE_PT = "font_size_pt"
    FIG_NUMBERING = "fig_numbering"
    DEFENSE_YEAR = "defense_year"
    RECENT_SOURCES_SHARE = "recent_sources_share"


class RubricParameters(StrictModel):
    """Validated values embedded in rubric metadata."""

    font_size_pt: int = Field(strict=True, ge=8, le=72)
    fig_numbering: Literal["сквозная", "по разделам"]
    defense_year: int = Field(strict=True, ge=2000, le=2100)
    recent_sources_share: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)


class ParameterOverrides(StrictModel):
    """Optional user-approved overrides for rubric parameters."""

    font_size_pt: int | None = Field(default=None, strict=True, ge=8, le=72)
    fig_numbering: Literal["сквозная", "по разделам"] | None = None
    defense_year: int | None = Field(default=None, strict=True, ge=2000, le=2100)
    recent_sources_share: float | None = Field(
        default=None,
        strict=True,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )


class RubricMeta(StrictModel):
    """Metadata whose vocabulary is fixed for rubric version 2025.1."""

    version: NonEmptyString
    sources: dict[str, NonEmptyString]
    layers: dict[str, NonEmptyString]
    severity: dict[str, NonEmptyString]
    policy: NonEmptyString
    params_to_approve: RubricParameters

    @model_validator(mode="after")
    def validate_vocabularies(self) -> Self:
        required_sources = {"M1", "M2", "DEP"}
        required_layers = {item.value for item in Capability}
        required_severities = {item.value for item in Severity}
        if set(self.sources) != required_sources:
            raise ValueError(f"meta.sources must contain exactly {sorted(required_sources)}")
        if set(self.layers) != required_layers:
            raise ValueError(f"meta.layers must contain exactly {sorted(required_layers)}")
        if set(self.severity) != required_severities:
            raise ValueError(f"meta.severity must contain exactly {sorted(required_severities)}")
        return self


class RubricRule(StrictModel):
    """One source rule before expansion."""

    id: RuleId
    src: NonEmptyString
    rule: NonEmptyString
    layer: NonEmptyString
    check: NonEmptyString
    severity: Severity
    severity_final: Severity | None = None


class Rubric(StrictModel):
    """Complete, source-preserving rubric contract."""

    meta: RubricMeta
    rules: tuple[RubricRule, ...]

    @model_validator(mode="after")
    def validate_rule_set(self) -> Self:
        if len(self.rules) != 64:
            raise ValueError(f"rubric must contain exactly 64 rules, got {len(self.rules)}")
        ids = [rule.id for rule in self.rules]
        duplicates = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate rule id(s): {', '.join(duplicates)}")
        return self


class LlmConfig(StrictModel):
    """Non-secret LLM settings retained by configuration validation."""

    provider: NonEmptyString = "disabled"
    model: NonEmptyString | None = None
    base_url: NonEmptyString | None = None
    allow_cloud_data: bool = False


class NormocontrolConfig(StrictModel):
    """Effective configuration after resolving local includes."""

    version: Literal[1]
    work_profile: WorkProfile
    rubric_path: Path = Path("rubric.yaml")
    output_dir: Path = Path("build/normocontrol")
    approved_params: tuple[ParameterName, ...] = ()
    params: ParameterOverrides = ParameterOverrides()
    llm: LlmConfig = LlmConfig()

    @model_validator(mode="after")
    def unique_approvals(self) -> Self:
        if len(set(self.approved_params)) != len(self.approved_params):
            raise ValueError("approved_params must not contain duplicates")
        return self


class ValidationWarning(StrictModel):
    """A non-blocking rubric validation diagnostic."""

    code: Literal["APPROVAL_REQUIRED", "PROFILE_MISMATCH"]
    message: NonEmptyString
    yaml_path: NonEmptyString


class EffectiveRule(StrictModel):
    """Profile-aware rule with normalized capabilities."""

    id: RuleId
    src: NonEmptyString
    rule: NonEmptyString
    layer: NonEmptyString
    capabilities: tuple[Capability, ...]
    check: NonEmptyString
    severity: Severity
    severity_final: Severity | None = None
    enabled: bool


class EffectiveRubric(StrictModel):
    """Validated rubric consumed by later execution stages."""

    meta: RubricMeta
    work_profile: WorkProfile
    rules: tuple[EffectiveRule, ...]
    warnings: tuple[ValidationWarning, ...] = ()
