"""Shared domain contracts for normocontrol checks."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Severity(StrEnum):
    """Finding severity used by formal and advisory checks."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    UNVERIFIABLE = "unverifiable"


class Finding(BaseModel):
    """Stable public representation of one normocontrol finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    severity: Severity
    message: str
    path: str | None = None
    page: int | None = None

