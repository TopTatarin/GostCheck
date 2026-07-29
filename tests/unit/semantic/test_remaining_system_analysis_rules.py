from __future__ import annotations

import pytest

from normocontrol.semantic.batching import BatchPlanner
from normocontrol.semantic.engine import RULE_SPECS, SemanticEngine
from normocontrol.semantic.schemas import (
    IMPLEMENTED_RULE_IDS,
    DiagnosticCode,
    SemanticStatus,
)

from .helpers import QueueProvider, make_bundle, response_payload

RULE_IDS = ("SSA-01", "SSA-02", "SSA-03")
SYSTEM_TITLE = "Модель as is"
SYSTEM_BODY = (
    "Текущая модель показана в нотации BPMN. "
    "Окружение описано таблицей система адрес протокол API. "
    "Структура данных содержит атрибут вид формат частоту единицу и пример."
)
TASK_TITLE = "Цель и задачи"
TASK_BODY = "Работа посвящена программной обработке вычислительных данных."
QUOTE = "Текущая модель показана в нотации"


def _bundle():
    return make_bundle(
        (
            (TASK_TITLE, TASK_BODY),
            (SYSTEM_TITLE, SYSTEM_BODY),
        )
    )


def _payload(rule_id: str, *, status: str, state: str) -> dict[str, object]:
    batch = BatchPlanner().plan(_bundle(), RULE_SPECS[rule_id])
    owner = next(chunk for chunk in batch.chunks if QUOTE in chunk.text)
    evidence = state != "absent"
    return response_payload(
        rule_id,
        RULE_SPECS[rule_id].elements,
        status=status,
        state=state,
        quote=QUOTE if evidence else None,
        chunk_id=owner.chunk_id if evidence else None,
    )


def test_remaining_system_analysis_rules_have_registered_specs() -> None:
    assert set(RULE_IDS) <= IMPLEMENTED_RULE_IDS
    for rule_id in RULE_IDS:
        spec = RULE_SPECS[rule_id]
        assert "system_analysis" in spec.section_roles
        assert spec.elements


def test_ssa_02_applicability_uses_direct_integration_evidence() -> None:
    requirement = RULE_SPECS["SSA-02"].requirement

    assert "системному анализу вместе" in requirement
    assert "интеграции означает программную тематику" in requirement
    assert "только при явном свидетельстве непрограммной тематики" in requirement


@pytest.mark.parametrize("rule_id", RULE_IDS)
@pytest.mark.parametrize(
    ("status", "state"),
    (("pass", "present"), ("warn", "absent"), ("warn", "weak")),
)
def test_remaining_system_analysis_positive_negative_and_partial(
    rule_id: str,
    status: str,
    state: str,
) -> None:
    finding = (
        SemanticEngine(QueueProvider([_payload(rule_id, status=status, state=state)]))
        .run(_bundle(), (rule_id,))
        .findings[0]
    )

    assert finding.status.value == status
    assert finding.diagnostic is None
    assert finding.status.value != "fail"


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_remaining_system_analysis_missing_section_skips_provider(rule_id: str) -> None:
    provider = QueueProvider([])

    finding = (
        SemanticEngine(provider)
        .run(
            make_bundle(((TASK_TITLE, TASK_BODY),)),
            (rule_id,),
        )
        .findings[0]
    )

    assert finding.status is SemanticStatus.NOT_APPLICABLE
    assert finding.diagnostic is DiagnosticCode.SECTION_MISSING
    assert provider.calls == []


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_remaining_system_analysis_accepts_alternative_heading(rule_id: str) -> None:
    batch = BatchPlanner().plan(_bundle(), RULE_SPECS[rule_id])

    assert SYSTEM_TITLE in {section.title for section in batch.sections}
    assert batch.missing_roles == ()


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_remaining_system_analysis_rejects_paraphrase(rule_id: str) -> None:
    batch = BatchPlanner().plan(_bundle(), RULE_SPECS[rule_id])
    owner = next(chunk for chunk in batch.chunks if QUOTE in chunk.text)
    payload = response_payload(
        rule_id,
        RULE_SPECS[rule_id].elements,
        quote="Текущая схема представлена как BPMN",
        chunk_id=owner.chunk_id,
    )

    finding = (
        SemanticEngine(QueueProvider([payload, payload]))
        .run(
            _bundle(),
            (rule_id,),
        )
        .findings[0]
    )

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.INVALID_EVIDENCE
    assert finding.evidence == ()


def test_duplicate_system_analysis_headings_are_selected_deterministically() -> None:
    bundle = make_bundle(
        (
            (TASK_TITLE, TASK_BODY),
            (SYSTEM_TITLE, SYSTEM_BODY),
            ("Системный анализ", "Повторный синтетический раздел с ограничениями."),
        )
    )

    first = BatchPlanner().plan(bundle, RULE_SPECS["SSA-01"])
    second = BatchPlanner().plan(bundle, RULE_SPECS["SSA-01"])

    assert first == second
    assert [section.title for section in first.sections] == [
        SYSTEM_TITLE,
        "Системный анализ",
    ]
