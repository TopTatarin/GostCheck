"""Merge-safe orchestration for structured semantic advisory checks."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from normocontrol.extract.base import DocumentBundle
from normocontrol.extract.chunking import estimate_tokens
from normocontrol.llm.base import LlmError, LlmProvider, LlmResponseError, LlmUnavailableError
from normocontrol.semantic.batching import BatchPlanner, RuleBatch, RuleSpec
from normocontrol.semantic.evidence import EvidenceVerifier, normalize_quote
from normocontrol.semantic.prompts import render_rule_prompt, repair_message
from normocontrol.semantic.rules.algorithm import ALG_01, ALG_03
from normocontrol.semantic.rules.annotation import ANN_01
from normocontrol.semantic.rules.architecture import ARC_01, ARC_02
from normocontrol.semantic.rules.cross_section import CON_01, TSK_01, TSK_03
from normocontrol.semantic.rules.implementation import IMP_01
from normocontrol.semantic.rules.introduction import INT_01
from normocontrol.semantic.rules.mathematics import MTH_02, MTH_03
from normocontrol.semantic.rules.results import RES_01
from normocontrol.semantic.rules.review import REV_05, REV_06
from normocontrol.semantic.rules.structure import STR_05
from normocontrol.semantic.rules.style import GEN_01, GEN_02
from normocontrol.semantic.rules.system_analysis import SSA_04
from normocontrol.semantic.rules.task_detail import TSK_02
from normocontrol.semantic.schemas import (
    IMPLEMENTED_RULE_IDS,
    SEMANTIC_RULE_IDS,
    BatchAudit,
    DiagnosticCode,
    ElementAssessment,
    ElementState,
    ResponseElementAssessment,
    SemanticFinding,
    SemanticReport,
    SemanticResponse,
    SemanticStatus,
    TokenUsage,
    VerifiedEvidence,
)

RULE_SPECS: dict[str, RuleSpec] = {
    spec.rule_id: spec
    for spec in (
        ALG_01,
        ALG_03,
        ANN_01,
        ARC_01,
        ARC_02,
        CON_01,
        GEN_01,
        GEN_02,
        IMP_01,
        INT_01,
        MTH_02,
        MTH_03,
        RES_01,
        REV_05,
        REV_06,
        SSA_04,
        STR_05,
        TSK_01,
        TSK_02,
        TSK_03,
    )
}


def _sorted_elements(
    elements: tuple[ResponseElementAssessment, ...],
) -> tuple[ElementAssessment, ...]:
    return tuple(
        ElementAssessment(
            element=element.element,
            state=element.state,
            evidence=tuple(
                sorted(
                    element.evidence,
                    key=lambda item: (item.chunk_id, normalize_quote(item.quote)),
                )
            ),
        )
        for element in sorted(elements, key=lambda item: item.element)
    )


class SemanticEngine:
    """Evaluate semantic rules in isolated batches and verify every quoted claim."""

    def __init__(
        self,
        provider: LlmProvider,
        *,
        model_id: str | None = None,
        planner: BatchPlanner | None = None,
        evidence_verifier: EvidenceVerifier | None = None,
    ) -> None:
        self._provider = provider
        self._model_id = (model_id or provider.name).strip()
        if not self._model_id:
            raise ValueError("model_id must not be empty")
        self._planner = planner or BatchPlanner()
        self._evidence_verifier = evidence_verifier or EvidenceVerifier()

    def run(
        self,
        bundle: DocumentBundle,
        rule_ids: Iterable[str] | None = None,
    ) -> SemanticReport:
        """Return a stable report; provider and evidence failures remain advisory."""
        selected = sorted(SEMANTIC_RULE_IDS if rule_ids is None else set(rule_ids))
        unknown = sorted(set(selected) - SEMANTIC_RULE_IDS)
        if unknown:
            raise ValueError(f"unknown semantic rule id(s): {', '.join(unknown)}")

        findings: list[SemanticFinding] = []
        audits: list[BatchAudit] = []
        for rule_id in selected:
            spec = RULE_SPECS.get(rule_id)
            if spec is None:
                findings.append(self._not_implemented(rule_id))
                continue
            batch = self._planner.plan(bundle, spec)
            if not batch.chunks or batch.missing_roles:
                findings.append(
                    SemanticFinding(
                        rule_id=rule_id,
                        status=SemanticStatus.NOT_APPLICABLE,
                        confidence=1.0,
                        summary="Подходящая секция отсутствует в DocumentBundle.",
                        diagnostic=DiagnosticCode.SECTION_MISSING,
                    )
                )
                continue
            finding, audit = self._evaluate(batch)
            findings.append(finding)
            audits.append(audit)

        return SemanticReport(findings=tuple(findings), batches=tuple(audits))

    @staticmethod
    def _not_implemented(rule_id: str) -> SemanticFinding:
        return SemanticFinding(
            rule_id=rule_id,
            status=SemanticStatus.NOT_APPLICABLE,
            confidence=1.0,
            summary="Семантическое правило запланировано для фазы расширения.",
            diagnostic=DiagnosticCode.NOT_IMPLEMENTED,
        )

    def _evaluate(self, batch: RuleBatch) -> tuple[SemanticFinding, BatchAudit]:
        rendered = render_rule_prompt(batch)
        messages = rendered.messages
        attempts = 0
        input_tokens = 0
        output_tokens = 0
        finding: SemanticFinding | None = None
        diagnostic = DiagnosticCode.INVALID_SCHEMA

        for attempt in range(2):
            request_messages = (
                messages if attempt == 0 else (*messages, repair_message(batch.spec.rule_id))
            )
            input_tokens += sum(estimate_tokens(message.content) for message in request_messages)
            attempts += 1
            try:
                raw = self._provider.request(request_messages, SemanticResponse)
                candidate = SemanticResponse.model_validate(raw)
                self._validate_response_for_batch(candidate, batch.spec)
                output_tokens += estimate_tokens(candidate.model_dump_json())
                verified = self._verified_finding(candidate, batch)
                if verified.diagnostic is DiagnosticCode.INVALID_EVIDENCE:
                    diagnostic = DiagnosticCode.INVALID_EVIDENCE
                    continue
                finding = verified
                break
            except LlmUnavailableError as error:
                if self._provider.name == "disabled":
                    diagnostic = DiagnosticCode.PROVIDER_DISABLED
                elif "timed out" in str(error).casefold():
                    diagnostic = DiagnosticCode.PROVIDER_TIMEOUT
                else:
                    diagnostic = DiagnosticCode.PROVIDER_ERROR
                break
            except (LlmResponseError, ValidationError, TypeError, ValueError):
                diagnostic = DiagnosticCode.INVALID_SCHEMA
                continue
            except LlmError:
                diagnostic = DiagnosticCode.PROVIDER_ERROR
                break

        if finding is None:
            finding = SemanticFinding(
                rule_id=batch.spec.rule_id,
                status=SemanticStatus.UNVERIFIABLE,
                confidence=0.0,
                summary=self._diagnostic_summary(diagnostic),
                diagnostic=diagnostic,
            )
        audit = BatchAudit(
            rule_id=batch.spec.rule_id,
            section_ids=tuple(sorted(batch.audit_section_ids)),
            chunk_ids=tuple(sorted(chunk.chunk_id for chunk in batch.chunks)),
            prompt_sha256=rendered.sha256,
            model_id=self._model_id,
            token_usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            attempts=attempts,
        )
        return finding, audit

    @staticmethod
    def _validate_response_for_batch(response: SemanticResponse, spec: RuleSpec) -> None:
        if response.rule_id != spec.rule_id:
            raise ValueError("response rule_id does not match requested rule")
        if response.status in {
            SemanticStatus.PASS,
            SemanticStatus.WARN,
            SemanticStatus.INFO,
        }:
            actual = {element.element for element in response.elements}
            if actual != set(spec.elements):
                raise ValueError("response elements do not match the rule specification")
        for element in response.elements:
            if element.state in {ElementState.PRESENT, ElementState.WEAK} and not element.evidence:
                raise ValueError("present and weak elements require evidence")

    def _verified_finding(
        self,
        response: SemanticResponse,
        batch: RuleBatch,
    ) -> SemanticFinding:
        checks = [self._evidence_verifier.verify(response.evidence, batch.chunks)]
        checks.extend(
            self._evidence_verifier.verify(element.evidence, batch.chunks)
            for element in response.elements
        )
        if any(not check.valid for check in checks):
            return SemanticFinding(
                rule_id=response.rule_id,
                status=SemanticStatus.UNVERIFIABLE,
                confidence=0.0,
                summary="Цитаты ответа не подтверждены разрешёнными фрагментами источника.",
                diagnostic=DiagnosticCode.INVALID_EVIDENCE,
            )

        unique: dict[tuple[str, str], VerifiedEvidence] = {}
        for check in checks:
            for item in check.evidence:
                unique[(item.chunk_id, normalize_quote(item.quote))] = item
        evidence = tuple(unique[key] for key in sorted(unique))
        return SemanticFinding(
            rule_id=response.rule_id,
            status=response.status,
            confidence=response.confidence,
            summary=response.summary,
            evidence=evidence,
            elements=_sorted_elements(response.elements),
        )

    @staticmethod
    def _diagnostic_summary(code: DiagnosticCode) -> str:
        summaries = {
            DiagnosticCode.PROVIDER_DISABLED: "LLM-провайдер отключён; проверка не выполнялась.",
            DiagnosticCode.PROVIDER_TIMEOUT: (
                "Истёк тайм-аут LLM-провайдера; результат нельзя проверить."
            ),
            DiagnosticCode.PROVIDER_ERROR: "LLM-провайдер недоступен; результат нельзя проверить.",
            DiagnosticCode.INVALID_SCHEMA: (
                "LLM дважды не вернул ответ по строгой схеме; результат нельзя проверить."
            ),
            DiagnosticCode.INVALID_RESPONSE: (
                "LLM дважды не вернул ответ по строгой схеме; результат нельзя проверить."
            ),
            DiagnosticCode.INVALID_EVIDENCE: (
                "LLM дважды вернул неподтверждённые цитаты; результат нельзя проверить."
            ),
        }
        return summaries.get(code, "Результат семантической проверки нельзя подтвердить.")


def implemented_rule_ids() -> tuple[str, ...]:
    """Expose the implemented vertical slice in stable order."""
    return tuple(sorted(IMPLEMENTED_RULE_IDS))
