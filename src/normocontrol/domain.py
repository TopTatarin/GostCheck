"""Stable public domain contracts for normocontrol checks."""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RuleLayer(StrEnum):
    """Execution layer used by rules in ``rubric.yaml``."""

    CLASS = "class"
    SCRIPT = "script"
    CLASS_SCRIPT = "class+script"
    LLM = "llm"
    VISION = "vision"


class Severity(StrEnum):
    """Importance assigned to a rule by the rubric."""

    ERROR = "error"
    WARN = "warn"
    INFO = "info"


class FindingStatus(StrEnum):
    """Outcome of evaluating one rule."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    INFO = "info"
    NOT_APPLICABLE = "not_applicable"
    UNVERIFIABLE = "unverifiable"
    SKIPPED = "skipped"


class ExitCode(IntEnum):
    """Documented process exit codes shared by CLI commands and reports."""

    SUCCESS = 0
    RUNTIME_ERROR = 1
    FORMAL_FAILURE = 2
    CONFIG_ERROR = 3
    INTERNAL_ERROR = 4


class ContractModel(BaseModel):
    """Base settings for all externally serialized project models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleDefinition(ContractModel):
    """Executable definition of one rubric rule."""

    rule_id: NonEmptyString
    description: NonEmptyString
    layer: RuleLayer
    severity: Severity
    enabled: bool = True


class Evidence(ContractModel):
    """A safe reference to evidence without embedding thesis content."""

    locator: NonEmptyString
    description: NonEmptyString | None = None


class Finding(ContractModel):
    """Result of evaluating a rule."""

    rule_id: NonEmptyString
    layer: RuleLayer
    severity: Severity
    status: FindingStatus
    message: NonEmptyString
    evidence: tuple[Evidence, ...] = ()
    path: str | None = None
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def prevent_advisory_failure(self) -> Self:
        """Keep nondeterministic layers advisory by construction."""
        if self.layer in {RuleLayer.LLM, RuleLayer.VISION}:
            allowed = {
                FindingStatus.WARN,
                FindingStatus.INFO,
                FindingStatus.NOT_APPLICABLE,
                FindingStatus.UNVERIFIABLE,
            }
            if self.status is FindingStatus.FAIL:
                msg = "LLM and vision findings cannot have status=fail"
                raise ValueError(msg)
            if self.status not in allowed:
                msg = "LLM and vision findings must use an advisory status"
                raise ValueError(msg)
        return self


class StageResult(ContractModel):
    """Result and timing information for one execution stage."""

    name: NonEmptyString
    findings: tuple[Finding, ...] = ()
    duration_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class RunReport(ContractModel):
    """Top-level, timestamp-free JSON report contract."""

    schema_version: str = "1.0"
    tool_version: str
    exit_code: ExitCode = ExitCode.SUCCESS
    stages: tuple[StageResult, ...] = ()

    @model_validator(mode="after")
    def validate_exit_code(self) -> Self:
        """Keep the serialized exit code consistent with formal findings."""
        has_formal_failure = any(
            finding.status is FindingStatus.FAIL
            for stage in self.stages
            for finding in stage.findings
        )
        if self.exit_code in {ExitCode.CONFIG_ERROR, ExitCode.INTERNAL_ERROR}:
            return self
        if has_formal_failure and self.exit_code is not ExitCode.FORMAL_FAILURE:
            msg = "formal fail findings require exit_code=2"
            raise ValueError(msg)
        if not has_formal_failure and self.exit_code is ExitCode.FORMAL_FAILURE:
            msg = "exit_code=2 requires at least one formal fail finding"
            raise ValueError(msg)
        return self
