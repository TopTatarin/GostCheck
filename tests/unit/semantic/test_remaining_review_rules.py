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

RULE_IDS = ("REV-02", "REV-04")
REVIEW_TITLE = "Литературный обзор"
REVIEW_BODY = (
    "Метаданные зарубежных статей содержат журнал и рецензирование. "
    "Учебники и непроверенные веб-публикации исключены."
)
QUOTE = "Метаданные зарубежных статей содержат журнал"


def _bundle():
    return make_bundle(((REVIEW_TITLE, REVIEW_BODY),))


def _payload(rule_id: str, *, status: str, state: str) -> dict[str, object]:
    batch = BatchPlanner().plan(_bundle(), RULE_SPECS[rule_id])
    evidence = state != "absent"
    return response_payload(
        rule_id,
        RULE_SPECS[rule_id].elements,
        status=status,
        state=state,
        quote=QUOTE if evidence else None,
        chunk_id=batch.chunks[0].chunk_id if evidence else None,
    )


def test_remaining_review_rules_have_strict_registered_specs() -> None:
    assert set(RULE_IDS) <= IMPLEMENTED_RULE_IDS
    for rule_id in RULE_IDS:
        spec = RULE_SPECS[rule_id]
        assert spec.section_roles == ("review",)
        assert spec.elements


@pytest.mark.parametrize("rule_id", RULE_IDS)
@pytest.mark.parametrize(
    ("status", "state"),
    (("pass", "present"), ("warn", "absent"), ("warn", "weak")),
)
def test_remaining_review_rules_positive_negative_and_partial(
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
def test_remaining_review_rules_missing_section_does_not_call_provider(rule_id: str) -> None:
    provider = QueueProvider([])

    finding = (
        SemanticEngine(provider)
        .run(
            make_bundle((("Введение", "Синтетический текст."),)),
            (rule_id,),
        )
        .findings[0]
    )

    assert finding.status is SemanticStatus.NOT_APPLICABLE
    assert finding.diagnostic is DiagnosticCode.SECTION_MISSING
    assert provider.calls == []


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_remaining_review_rules_accept_alternative_heading(rule_id: str) -> None:
    finding = (
        SemanticEngine(QueueProvider([_payload(rule_id, status="pass", state="present")]))
        .run(_bundle(), (rule_id,))
        .findings[0]
    )

    assert finding.status is SemanticStatus.PASS
    assert finding.evidence


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_remaining_review_rules_reject_quote_from_other_section(rule_id: str) -> None:
    payload = response_payload(
        rule_id,
        RULE_SPECS[rule_id].elements,
        quote="Точная цитата только из введения",
        chunk_id="introduction:1",
    )
    bundle = make_bundle(
        (
            ("Введение", "Точная цитата только из введения."),
            (REVIEW_TITLE, REVIEW_BODY),
        )
    )

    finding = (
        SemanticEngine(QueueProvider([payload, payload]))
        .run(
            bundle,
            (rule_id,),
        )
        .findings[0]
    )

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.INVALID_EVIDENCE
    assert finding.evidence == ()
