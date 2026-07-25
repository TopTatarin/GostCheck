"""Reproducible quality metrics for the synthetic semantic regression corpus."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from normocontrol.extract.base import (
    DocumentBundle,
    ExtractedDocument,
    ExtractionQuality,
    HeadingCandidate,
    SourceFile,
    SourceFormat,
    sha256_text,
)
from normocontrol.extract.chunking import Chunker
from normocontrol.extract.sections import SectionDetector
from normocontrol.llm.base import ChatMessage, LlmProvider, ProbeResult
from normocontrol.semantic.engine import RULE_SPECS, SemanticEngine
from normocontrol.semantic.evidence import normalize_quote
from normocontrol.semantic.schemas import (
    IMPLEMENTED_RULE_IDS,
    DiagnosticCode,
    ElementState,
    EvidenceQuote,
    SemanticResponse,
    SemanticStatus,
    SupportedElementAssessment,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_REQUIRED_SECTION_TITLES = frozenset(
    {
        "аннотация",
        "введение",
        "постановка задачи",
        "анализ результатов",
        "заключение",
    }
)


class StrictModel(BaseModel):
    """Immutable local evaluation contract with unknown fields forbidden."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedOutcome(StrEnum):
    """Human annotation assigned to one fixture/rule pair."""

    POSITIVE = "positive"
    WARNING = "warning"
    INSUFFICIENT = "insufficient"


class SyntheticSection(StrictModel):
    """One complete synthetic document section."""

    title: NonEmptyString
    body: NonEmptyString


class SemanticExpectation(StrictModel):
    """Expected quality class and a source-backed quote for deterministic mocks."""

    rule_id: NonEmptyString
    outcome: ExpectedOutcome
    evidence_quote: NonEmptyString | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def evidence_matches_outcome(self) -> Self:
        if self.rule_id not in IMPLEMENTED_RULE_IDS:
            raise ValueError("expectation rule_id is not implemented")
        if self.outcome is ExpectedOutcome.INSUFFICIENT:
            if self.evidence_quote is not None:
                raise ValueError("insufficient expectations must not prescribe evidence")
        elif self.evidence_quote is None:
            raise ValueError("positive and warning expectations require exact evidence")
        return self


class SyntheticSemanticFixture(StrictModel):
    """A fully sectioned synthetic thesis and annotations for all six rules."""

    id: NonEmptyString
    sections: tuple[SyntheticSection, ...]
    expectations: tuple[SemanticExpectation, ...]

    @model_validator(mode="after")
    def complete_document_and_rules(self) -> Self:
        titles = {section.title.casefold() for section in self.sections}
        if not titles >= _REQUIRED_SECTION_TITLES:
            raise ValueError("fixture must contain all required semantic sections")
        rule_ids = [item.rule_id for item in self.expectations]
        if rule_ids != sorted(rule_ids) or set(rule_ids) != IMPLEMENTED_RULE_IDS:
            raise ValueError("fixture expectations must cover all implemented rules in order")
        return self


class SyntheticSemanticCorpus(StrictModel):
    """Versioned corpus with complete positive/warning/insufficient coverage."""

    schema_version: str = "1.0"
    corpus_id: NonEmptyString
    fixtures: tuple[SyntheticSemanticFixture, ...]

    @model_validator(mode="after")
    def complete_coverage(self) -> Self:
        fixture_ids = [fixture.id for fixture in self.fixtures]
        if fixture_ids != sorted(fixture_ids) or len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("fixture ids must be unique and sorted")
        coverage = {
            rule_id: {
                expectation.outcome
                for fixture in self.fixtures
                for expectation in fixture.expectations
                if expectation.rule_id == rule_id
            }
            for rule_id in IMPLEMENTED_RULE_IDS
        }
        required = set(ExpectedOutcome)
        if any(outcomes != required for outcomes in coverage.values()):
            raise ValueError("each implemented rule requires positive, warning and insufficient")
        return self


class SemanticObservation(StrictModel):
    """Text-free outcome for one corpus/rule evaluation."""

    fixture_id: NonEmptyString
    rule_id: NonEmptyString
    expected: ExpectedOutcome
    status: SemanticStatus
    diagnostic: DiagnosticCode | None
    schema_valid: bool
    evidence_valid: bool
    useful_advisory: bool


class SemanticRuleMetrics(StrictModel):
    """Required quality rates for one implemented semantic rule."""

    rule_id: NonEmptyString
    cases: int = Field(ge=1)
    actionable_cases: int = Field(ge=1)
    schema_valid_count: int = Field(ge=0)
    evidence_valid_count: int = Field(ge=0)
    useful_advisory_count: int = Field(ge=0)
    schema_valid_rate: float = Field(ge=0, le=1)
    evidence_valid_rate: float = Field(ge=0, le=1)
    useful_advisory_rate: float = Field(ge=0, le=1)


class SemanticEvaluationReport(StrictModel):
    """Deterministic, privacy-safe evaluation artifact."""

    schema_version: str = "1.0"
    corpus_id: NonEmptyString
    corpus_sha256: NonEmptyString
    provider: NonEmptyString
    model_id: NonEmptyString
    observations: tuple[SemanticObservation, ...]
    rules: tuple[SemanticRuleMetrics, ...]


ProviderFactory = Callable[
    [SyntheticSemanticFixture, SemanticExpectation, DocumentBundle],
    LlmProvider,
]


def load_semantic_corpus(path: Path) -> SyntheticSemanticCorpus:
    """Load a strict synthetic corpus without accepting arbitrary document paths."""
    return SyntheticSemanticCorpus.model_validate_json(path.read_text(encoding="utf-8"))


def semantic_corpus_sha256(corpus: SyntheticSemanticCorpus) -> str:
    """Hash canonical annotations and text so repeated runs identify identical input."""
    canonical = json.dumps(
        corpus.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_synthetic_bundle(fixture: SyntheticSemanticFixture) -> DocumentBundle:
    """Build a normal DocumentBundle from in-memory synthetic fixture text."""
    text = "\n\n".join(f"{section.title}\n{section.body}" for section in fixture.sections)
    headings: list[HeadingCandidate] = []
    cursor = 0
    for section in fixture.sections:
        char_start = text.index(section.title, cursor)
        headings.append(
            HeadingCandidate(
                title=section.title,
                level=1,
                char_start=char_start,
                origin="synthetic_fixture",
            )
        )
        cursor = char_start + len(section.title)
    source_hash = sha256_text(text)
    extracted = ExtractedDocument(
        source_format=SourceFormat.LATEX,
        source_hash=source_hash,
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(
            SourceFile(
                path=f"synthetic/{fixture.id}.tex",
                sha256=sha256_text(f"synthetic fixture {fixture.id}"),
            ),
        ),
        headings=tuple(headings),
    )
    sections = SectionDetector().detect(extracted)
    return DocumentBundle(
        source_format=extracted.source_format,
        source_hash=extracted.source_hash,
        text=extracted.text,
        extraction_quality=extracted.extraction_quality,
        source_files=extracted.source_files,
        sections=sections,
        chunks=Chunker(token_budget=800).chunk(extracted, sections),
    )


class AnnotatedSemanticProvider(LlmProvider):
    """Deterministic provider driven only by checked-in synthetic annotations."""

    def __init__(
        self,
        expectation: SemanticExpectation,
        bundle: DocumentBundle,
    ) -> None:
        self._expectation = expectation
        self._bundle = bundle

    @property
    def name(self) -> str:
        return "synthetic-mock"

    def health_check(self) -> ProbeResult:
        return ProbeResult(
            provider=self.name,
            available=True,
            model_available=True,
            schema_available=True,
            detail="deterministic synthetic annotations",
        )

    def request[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> ResponseT:
        del messages
        spec = RULE_SPECS[self._expectation.rule_id]
        if self._expectation.outcome is ExpectedOutcome.INSUFFICIENT:
            response = SemanticResponse(
                rule_id=self._expectation.rule_id,
                status=SemanticStatus.UNVERIFIABLE,
                confidence=0.0,
                summary="Синтетических данных недостаточно для подтверждённого вывода.",
                evidence=(),
                elements=(),
            )
            return response_model.model_validate(response.model_dump())

        quote = self._expectation.evidence_quote
        if quote is None:
            raise ValueError("annotated evidence is missing")
        normalized = normalize_quote(quote)
        owner = next(
            (chunk for chunk in self._bundle.chunks if normalized in normalize_quote(chunk.text)),
            None,
        )
        if owner is None:
            raise ValueError("annotated evidence is outside fixture chunks")
        evidence = (EvidenceQuote(chunk_id=owner.chunk_id, quote=quote),)
        state: Literal[ElementState.PRESENT, ElementState.WEAK] = (
            ElementState.PRESENT
            if self._expectation.outcome is ExpectedOutcome.POSITIVE
            else ElementState.WEAK
        )
        status = (
            SemanticStatus.PASS
            if self._expectation.outcome is ExpectedOutcome.POSITIVE
            else SemanticStatus.WARN
        )
        response = SemanticResponse(
            rule_id=self._expectation.rule_id,
            status=status,
            confidence=0.95 if status is SemanticStatus.PASS else 0.6,
            summary="Синтетическая аннотация даёт проверяемый консультативный результат.",
            evidence=evidence,
            elements=tuple(
                SupportedElementAssessment(element=element, state=state, evidence=evidence)
                for element in spec.elements
            ),
        )
        return response_model.model_validate(response.model_dump())


def mock_provider_factory(
    fixture: SyntheticSemanticFixture,
    expectation: SemanticExpectation,
    bundle: DocumentBundle,
) -> LlmProvider:
    """Create the deterministic provider used by offline evaluation."""
    del fixture
    return AnnotatedSemanticProvider(expectation, bundle)


def shared_provider_factory(provider: LlmProvider) -> ProviderFactory:
    """Reuse one configured live provider for every corpus observation."""

    def factory(
        fixture: SyntheticSemanticFixture,
        expectation: SemanticExpectation,
        bundle: DocumentBundle,
    ) -> LlmProvider:
        del fixture, expectation, bundle
        return provider

    return factory


def _observation(
    fixture: SyntheticSemanticFixture,
    expectation: SemanticExpectation,
    provider: LlmProvider,
    bundle: DocumentBundle,
    *,
    model_id: str,
) -> SemanticObservation:
    report = SemanticEngine(provider, model_id=model_id).run(bundle, (expectation.rule_id,))
    finding = report.findings[0]
    schema_invalid = {
        DiagnosticCode.INVALID_SCHEMA,
        DiagnosticCode.INVALID_RESPONSE,
        DiagnosticCode.PROVIDER_DISABLED,
        DiagnosticCode.PROVIDER_ERROR,
        DiagnosticCode.PROVIDER_TIMEOUT,
        DiagnosticCode.SECTION_MISSING,
    }
    schema_valid = finding.diagnostic not in schema_invalid
    actionable = expectation.outcome is not ExpectedOutcome.INSUFFICIENT
    evidence_valid = (
        schema_valid
        and finding.diagnostic is not DiagnosticCode.INVALID_EVIDENCE
        and (not actionable or bool(finding.evidence))
    )
    useful = (
        actionable
        and finding.diagnostic is None
        and finding.status in {SemanticStatus.PASS, SemanticStatus.WARN, SemanticStatus.INFO}
        and evidence_valid
    )
    return SemanticObservation(
        fixture_id=fixture.id,
        rule_id=expectation.rule_id,
        expected=expectation.outcome,
        status=finding.status,
        diagnostic=finding.diagnostic,
        schema_valid=schema_valid,
        evidence_valid=evidence_valid,
        useful_advisory=useful,
    )


def evaluate_semantic_corpus(
    corpus: SyntheticSemanticCorpus,
    *,
    provider_factory: ProviderFactory,
    provider_name: str,
    model_id: str,
) -> SemanticEvaluationReport:
    """Evaluate all annotated pairs and aggregate stable per-rule rates."""
    observations: list[SemanticObservation] = []
    for fixture in corpus.fixtures:
        bundle = build_synthetic_bundle(fixture)
        for expectation in fixture.expectations:
            provider = provider_factory(fixture, expectation, bundle)
            observations.append(
                _observation(
                    fixture,
                    expectation,
                    provider,
                    bundle,
                    model_id=model_id,
                )
            )
    ordered = tuple(sorted(observations, key=lambda item: (item.rule_id, item.fixture_id)))
    metrics: list[SemanticRuleMetrics] = []
    for rule_id in sorted(IMPLEMENTED_RULE_IDS):
        items = tuple(item for item in ordered if item.rule_id == rule_id)
        actionable = tuple(
            item for item in items if item.expected is not ExpectedOutcome.INSUFFICIENT
        )
        schema_count = sum(item.schema_valid for item in items)
        evidence_count = sum(item.evidence_valid for item in items)
        useful_count = sum(item.useful_advisory for item in actionable)
        metrics.append(
            SemanticRuleMetrics(
                rule_id=rule_id,
                cases=len(items),
                actionable_cases=len(actionable),
                schema_valid_count=schema_count,
                evidence_valid_count=evidence_count,
                useful_advisory_count=useful_count,
                schema_valid_rate=schema_count / len(items),
                evidence_valid_rate=evidence_count / len(items),
                useful_advisory_rate=useful_count / len(actionable),
            )
        )
    return SemanticEvaluationReport(
        corpus_id=corpus.corpus_id,
        corpus_sha256=semantic_corpus_sha256(corpus),
        provider=provider_name,
        model_id=model_id,
        observations=ordered,
        rules=tuple(metrics),
    )
