from __future__ import annotations

import json
from pathlib import Path

import pytest

from normocontrol.llm.base import LlmUnavailableError
from normocontrol.llm.disabled import DisabledProvider
from normocontrol.semantic.batching import BatchPlanner
from normocontrol.semantic.engine import RULE_SPECS, SemanticEngine
from normocontrol.semantic.prompts import render_rule_prompt
from normocontrol.semantic.schemas import DiagnosticCode, SemanticStatus

from .helpers import SECTION_PARTS, QueueProvider, make_bundle, response_payload

BATCH2_RULE_IDS = ("ALG-03", "ARC-01", "ARC-02", "GEN-02", "IMP-01", "MTH-03", "RES-01")
GOLDEN = json.loads(
    Path("tests/fixtures/semantic/golden_responses.json").read_text(encoding="utf-8")
)
SECTION_TITLE = {
    "ALG-03": "Алгоритм",
    "ARC-01": "Архитектурно-техническое решение",
    "ARC-02": "Архитектурно-техническое решение",
    "GEN-02": "Программная реализация",
    "IMP-01": "Программная реализация",
    "MTH-03": "Математическая модель",
    "RES-01": "Анализ результатов",
}
EXPECTED_CROSS_SECTION_TITLES = {
    "ARC-01": {"Структурный системный анализ", "Архитектурно-техническое решение"},
    "ARC-02": {"Постановка задачи", "Архитектурно-техническое решение"},
    "IMP-01": {
        "Архитектурно-техническое решение",
        "Программная реализация",
        "Анализ результатов",
    },
    "MTH-03": {"Постановка задачи", "Математическая модель", "Анализ результатов"},
    "RES-01": {"Постановка задачи", "Анализ результатов"},
}


def _valid_payload(
    rule_id: str,
    *,
    status: str = "pass",
    state: str = "present",
) -> dict[str, object]:
    golden = GOLDEN[rule_id]
    return response_payload(
        rule_id,
        RULE_SPECS[rule_id].elements,
        status=status,
        state=state,
        quote=golden["quote"],
        chunk_id=golden["chunk_id"],
    )


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
def test_batch2_rule_prompt_contract_is_scoped_and_complete(rule_id: str) -> None:
    spec = RULE_SPECS[rule_id]
    batch = BatchPlanner().plan(make_bundle(), spec)

    rendered = render_rule_prompt(batch)
    user_prompt = rendered.messages[1].content

    assert spec.rule_id in user_prompt
    assert spec.requirement in user_prompt
    assert all(element in user_prompt for element in spec.elements)
    assert 0 < len(batch.chunks) <= spec.max_total_chunks
    assert "UNTRUSTED_DOCUMENT_DATA" in user_prompt


@pytest.mark.parametrize(
    ("rule_id", "expected_titles"),
    EXPECTED_CROSS_SECTION_TITLES.items(),
)
def test_batch2_cross_section_rules_select_every_required_section(
    rule_id: str,
    expected_titles: set[str],
) -> None:
    batch = BatchPlanner().plan(make_bundle(), RULE_SPECS[rule_id])

    assert {section.title for section in batch.sections} == expected_titles
    assert batch.missing_roles == ()


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
@pytest.mark.parametrize(
    ("status", "state"),
    (("pass", "present"), ("warn", "weak"), ("warn", "absent")),
)
def test_batch2_complete_partial_and_missing_element_outcomes(
    rule_id: str,
    status: str,
    state: str,
) -> None:
    payload = _valid_payload(rule_id, status=status, state=state)
    if state == "absent":
        for element in payload["elements"]:  # type: ignore[index]
            element["evidence"] = []
        payload["evidence"] = []

    finding = SemanticEngine(QueueProvider([payload])).run(make_bundle(), (rule_id,)).findings[0]

    assert finding.status.value == status
    assert finding.diagnostic is None
    assert finding.status.value != "fail"


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
def test_batch2_missing_section_is_diagnostic_without_provider_call(rule_id: str) -> None:
    provider = QueueProvider([])
    bundle = make_bundle((("Аннотация", "Только синтетическая аннотация."),))

    finding = SemanticEngine(provider).run(bundle, (rule_id,)).findings[0]

    assert finding.status is SemanticStatus.NOT_APPLICABLE
    assert finding.diagnostic is DiagnosticCode.SECTION_MISSING
    assert provider.calls == []


@pytest.mark.parametrize("rule_id", EXPECTED_CROSS_SECTION_TITLES)
def test_batch2_one_missing_cross_section_is_diagnostic(rule_id: str) -> None:
    omitted = next(iter(EXPECTED_CROSS_SECTION_TITLES[rule_id]))
    parts = tuple(part for part in SECTION_PARTS if part[0] != omitted)
    provider = QueueProvider([])

    report = SemanticEngine(provider).run(make_bundle(parts), (rule_id,))

    assert report.findings[0].diagnostic is DiagnosticCode.SECTION_MISSING
    assert provider.calls == []


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
def test_batch2_exact_quote_is_verified(rule_id: str) -> None:
    finding = SemanticEngine(QueueProvider([_valid_payload(rule_id)])).run(
        make_bundle(), (rule_id,)
    ).findings[0]

    assert finding.status is SemanticStatus.PASS
    assert finding.evidence
    assert all(item.locator.startswith("sha256:") for item in finding.evidence)


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
@pytest.mark.parametrize("mode", ("fabricated", "wrong_chunk"))
def test_batch2_fabricated_quote_and_wrong_chunk_are_removed(
    rule_id: str,
    mode: str,
) -> None:
    golden = GOLDEN[rule_id]
    quote = "полностью выдуманная цитата" if mode == "fabricated" else golden["quote"]
    chunk_id = golden["chunk_id"] if mode == "fabricated" else "annotation:1"
    payload = response_payload(
        rule_id,
        RULE_SPECS[rule_id].elements,
        quote=quote,
        chunk_id=chunk_id,
    )

    report = SemanticEngine(QueueProvider([payload, payload])).run(make_bundle(), (rule_id,))
    finding = report.findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.INVALID_EVIDENCE
    assert finding.evidence == ()
    assert report.batches[0].attempts == 2


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
@pytest.mark.parametrize("mode", ("duplicate_element", "missing_element", "unknown_field", "fail"))
def test_batch2_strict_schema_rejects_invalid_rule_outputs(rule_id: str, mode: str) -> None:
    payload = _valid_payload(rule_id)
    elements = payload["elements"]
    assert isinstance(elements, list)
    if mode == "duplicate_element":
        elements.append(elements[0])
    elif mode == "missing_element":
        elements.pop()
    elif mode == "unknown_field":
        payload["unexpected"] = "forbidden"
    else:
        payload["status"] = "fail"
    provider = QueueProvider([payload, payload])

    finding = SemanticEngine(provider).run(make_bundle(), (rule_id,)).findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.INVALID_SCHEMA
    assert len(provider.calls) == 2


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
def test_batch2_invalid_json_uses_one_repair_attempt(rule_id: str) -> None:
    provider = QueueProvider(["{invalid-json", _valid_payload(rule_id)])

    report = SemanticEngine(provider).run(make_bundle(), (rule_id,))

    assert report.findings[0].status is SemanticStatus.PASS
    assert report.batches[0].attempts == 2
    assert len(provider.calls[1]) == 3


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
@pytest.mark.parametrize(
    ("error", "diagnostic"),
    (
        (LlmUnavailableError("synthetic provider unavailable"), DiagnosticCode.PROVIDER_ERROR),
        (LlmUnavailableError("synthetic request timed out"), DiagnosticCode.PROVIDER_TIMEOUT),
    ),
)
def test_batch2_provider_failures_remain_advisory(
    rule_id: str,
    error: Exception,
    diagnostic: DiagnosticCode,
) -> None:
    finding = SemanticEngine(QueueProvider([error])).run(make_bundle(), (rule_id,)).findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is diagnostic


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
def test_batch2_disabled_provider_is_offline_advisory(rule_id: str) -> None:
    finding = SemanticEngine(DisabledProvider()).run(make_bundle(), (rule_id,)).findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.PROVIDER_DISABLED


@pytest.mark.parametrize("rule_id", BATCH2_RULE_IDS)
def test_batch2_unicode_long_document_is_bounded_and_verified(rule_id: str) -> None:
    golden = GOLDEN[rule_id]
    long_body = (
        f"{golden['quote']}. Ёлка, café и Δ используются только в синтетическом тексте. "
        + " ".join(f"Синтетический фрагмент номер {index}." for index in range(400))
    )
    parts = tuple(
        (title, long_body if title == SECTION_TITLE[rule_id] else body)
        for title, body in SECTION_PARTS
    )
    payload = response_payload(
        rule_id,
        RULE_SPECS[rule_id].elements,
        quote=golden["quote"],
        chunk_id=golden["chunk_id"],
    )

    report = SemanticEngine(QueueProvider([payload])).run(make_bundle(parts), (rule_id,))

    assert report.findings[0].status is SemanticStatus.PASS
    assert len(report.batches[0].chunk_ids) <= RULE_SPECS[rule_id].max_total_chunks
    assert report.batches[0].token_usage.usage_source == "local_deterministic_estimate"


def test_batch2_findings_and_audits_are_stably_sorted_text_safe_and_never_fail() -> None:
    responses = [_valid_payload(rule_id) for rule_id in BATCH2_RULE_IDS]

    report = SemanticEngine(QueueProvider(responses)).run(
        make_bundle(),
        reversed(BATCH2_RULE_IDS),
    )

    assert [item.rule_id for item in report.findings] == list(BATCH2_RULE_IDS)
    assert [item.rule_id for item in report.batches] == list(BATCH2_RULE_IDS)
    assert all(item.status.value != "fail" for item in report.findings)
    audit_json = "\n".join(item.model_dump_json() for item in report.batches)
    assert "local_deterministic_estimate" in audit_json
    assert "Модель to be устраняет выявленную проблему" not in audit_json
