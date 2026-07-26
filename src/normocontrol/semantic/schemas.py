"""Strict public contracts for advisory semantic checks."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RuleId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}-[0-9]{2}$")]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

IMPLEMENTED_RULE_IDS = frozenset(
    {
        "ALG-01",
        "ANN-01",
        "CON-01",
        "GEN-01",
        "INT-01",
        "MTH-02",
        "REV-05",
        "REV-06",
        "SSA-04",
        "TSK-01",
        "TSK-02",
        "TSK-03",
    }
)

# Every current rubric rule whose layer contains the LLM capability. Keeping this
# vocabulary explicit makes an unsupported rule visible instead of silently passing it.
SEMANTIC_RULE_IDS = frozenset(
    {
        "ALG-01",
        "ALG-03",
        "ANN-01",
        "ARC-01",
        "ARC-02",
        "CON-01",
        "GEN-01",
        "GEN-02",
        "IMP-01",
        "INT-01",
        "MTH-02",
        "MTH-03",
        "RES-01",
        "REV-02",
        "REV-04",
        "REV-05",
        "REV-06",
        "SSA-01",
        "SSA-02",
        "SSA-03",
        "SSA-04",
        "STR-05",
        "TSK-01",
        "TSK-02",
        "TSK-03",
    }
)


class StrictModel(BaseModel):
    """Immutable model which rejects unknown generated fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class SemanticStatus(StrEnum):
    """Advisory-only response statuses; ``fail`` is intentionally impossible."""

    PASS = "pass"
    WARN = "warn"
    INFO = "info"
    NOT_APPLICABLE = "not_applicable"
    UNVERIFIABLE = "unverifiable"


class ElementState(StrEnum):
    """Presence of one structured rubric element."""

    PRESENT = "present"
    WEAK = "weak"
    ABSENT = "absent"
    NOT_APPLICABLE = "not_applicable"


class DiagnosticCode(StrEnum):
    """Stable reason codes produced by the deterministic semantic wrapper."""

    NOT_IMPLEMENTED = "not_implemented"
    SECTION_MISSING = "section_missing"
    PROVIDER_DISABLED = "provider_disabled"
    PROVIDER_ERROR = "provider_error"
    PROVIDER_TIMEOUT = "provider_timeout"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_RESPONSE = "invalid_response"
    INVALID_EVIDENCE = "invalid_evidence"


def _word_count(value: str) -> int:
    return len(re.findall(r"\w+(?:[-'’]\w+)*", value, flags=re.UNICODE))


def _reject_markup(value: str) -> str:
    if "```" in value or re.search(r"<\s*/?\s*[a-z][^>]*>", value, re.IGNORECASE):
        raise ValueError("HTML and markdown fences are not allowed")
    return value


class EvidenceQuote(StrictModel):
    """A short model-supplied quote that still has to pass source verification."""

    chunk_id: Annotated[NonEmptyString, Field(alias="i")]
    quote: Annotated[NonEmptyString, Field(alias="q", max_length=64)]

    @field_validator("quote")
    @classmethod
    def bounded_quote(cls, value: str) -> str:
        """Keep ANN/INT evidence within their ten-word rubric contract.

        The same conservative bound is applied to every implemented rule so that a
        future rule cannot accidentally disclose a large source fragment.
        """
        if _word_count(value) > 10:
            raise ValueError("evidence quote must contain at most 10 words")
        return _reject_markup(value)


class ElementAssessment(StrictModel):
    """Structured decision for one named rubric element."""

    element: NonEmptyString
    state: ElementState
    evidence: tuple[EvidenceQuote, ...] = ()


class SupportedElementAssessment(StrictModel):
    """Generated present/weak element with exactly one verifiable quote."""

    element: Annotated[NonEmptyString, Field(alias="n")]
    state: Annotated[Literal[ElementState.PRESENT, ElementState.WEAK], Field(alias="s")]
    evidence: Annotated[
        tuple[EvidenceQuote, ...],
        Field(alias="q", min_length=1, max_length=1),
    ]


class UnsupportedElementAssessment(StrictModel):
    """Generated absent/not-applicable element which cannot invent evidence."""

    element: Annotated[NonEmptyString, Field(alias="n")]
    state: Annotated[
        Literal[ElementState.ABSENT, ElementState.NOT_APPLICABLE],
        Field(alias="s"),
    ]
    evidence: Annotated[tuple[EvidenceQuote, ...], Field(alias="q", max_length=0)]


type ResponseElementAssessment = Annotated[
    SupportedElementAssessment | UnsupportedElementAssessment,
    Field(discriminator="state"),
]


class SemanticResponse(StrictModel):
    """The only response schema requested from an LLM."""

    rule_id: Annotated[RuleId, Field(alias="r")]
    status: Annotated[SemanticStatus, Field(alias="s")]
    confidence: Annotated[
        float,
        Field(alias="c", strict=True, ge=0, le=1, allow_inf_nan=False),
    ]
    summary: Annotated[NonEmptyString, Field(alias="m", max_length=500)]
    evidence: Annotated[tuple[EvidenceQuote, ...], Field(alias="q")]
    elements: Annotated[tuple[ResponseElementAssessment, ...], Field(alias="e")]

    @field_validator("rule_id")
    @classmethod
    def implemented_rule_only(cls, value: str) -> str:
        if value not in IMPLEMENTED_RULE_IDS:
            raise ValueError("response rule_id is not implemented")
        return value

    @field_validator("summary")
    @classmethod
    def plain_summary(cls, value: str) -> str:
        return _reject_markup(value)

    @model_validator(mode="after")
    def validate_elements(self) -> Self:
        names = [item.element.casefold() for item in self.elements]
        if len(names) != len(set(names)):
            raise ValueError("element names must be unique")
        return self


class VerifiedEvidence(StrictModel):
    """Evidence retained only after deterministic source verification."""

    chunk_id: NonEmptyString
    quote: NonEmptyString
    locator: NonEmptyString


class SemanticFinding(StrictModel):
    """Stable, merge-safe result for one semantic rubric rule."""

    rule_id: RuleId
    status: SemanticStatus
    confidence: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    summary: NonEmptyString
    evidence: tuple[VerifiedEvidence, ...] = ()
    elements: tuple[ElementAssessment, ...] = ()
    diagnostic: DiagnosticCode | None = None

    @model_validator(mode="after")
    def advisory_invariants(self) -> Self:
        if self.rule_id not in SEMANTIC_RULE_IDS:
            raise ValueError("finding rule_id is not a semantic rubric rule")
        if self.diagnostic is DiagnosticCode.NOT_IMPLEMENTED:
            if self.rule_id in IMPLEMENTED_RULE_IDS:
                raise ValueError("implemented rules cannot be marked not_implemented")
            if self.status is not SemanticStatus.NOT_APPLICABLE:
                raise ValueError("not_implemented rules must be not_applicable")
        return self


class TokenUsage(StrictModel):
    """Locally estimated token accounting stored without request or response text."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    usage_source: Literal["local_deterministic_estimate"] = "local_deterministic_estimate"

    @model_validator(mode="after")
    def total_matches(self) -> Self:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self


class BatchAudit(StrictModel):
    """Non-sensitive audit record for one rule request."""

    rule_id: RuleId
    section_ids: tuple[NonEmptyString, ...]
    chunk_ids: tuple[NonEmptyString, ...]
    prompt_sha256: SHA256
    model_id: NonEmptyString
    token_usage: TokenUsage
    attempts: int = Field(ge=0, le=2)


class SemanticReport(StrictModel):
    """Deterministically ordered semantic-stage report."""

    schema_version: str = "1.0"
    findings: tuple[SemanticFinding, ...]
    batches: tuple[BatchAudit, ...] = ()

    @model_validator(mode="after")
    def deterministic_order(self) -> Self:
        finding_ids = [item.rule_id for item in self.findings]
        batch_ids = [item.rule_id for item in self.batches]
        if finding_ids != sorted(finding_ids) or len(finding_ids) != len(set(finding_ids)):
            raise ValueError("findings must be uniquely sorted by rule_id")
        if batch_ids != sorted(batch_ids) or len(batch_ids) != len(set(batch_ids)):
            raise ValueError("batches must be uniquely sorted by rule_id")
        return self
