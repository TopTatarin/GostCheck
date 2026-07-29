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

from .helpers import QueueProvider, make_bundle, response_payload

RULE_ID = "STR-05"
GOLDEN = json.loads(
    Path("tests/fixtures/semantic/golden_responses.json").read_text(encoding="utf-8")
)[RULE_ID]
HEADING = "Сравнение методов локальной проверки"
SECRET_BODY = "Этот синтетический текст подраздела не должен попадать в prompt."
HEADING_PARTS = (
    ("Обзор научно-технической информации", "Синтетический обзор."),
    (HEADING, SECRET_BODY),
    ("Критерии воспроизводимости", "Ещё один синтетический текст."),
)
HEADING_LEVELS = (1, 2, 2)


def _heading_bundle():
    return make_bundle(HEADING_PARTS, levels=HEADING_LEVELS)


def _valid_payload(
    *,
    status: str = "pass",
    state: str = "present",
) -> dict[str, object]:
    return response_payload(
        RULE_ID,
        RULE_SPECS[RULE_ID].elements,
        status=status,
        state=state,
        quote=GOLDEN["quote"],
        chunk_id=GOLDEN["chunk_id"],
    )


def test_str05_prompt_contains_only_bounded_subsection_headings() -> None:
    spec = RULE_SPECS[RULE_ID]
    batch = BatchPlanner().plan(_heading_bundle(), spec)

    rendered = render_rule_prompt(batch)
    user_prompt = rendered.messages[1].content

    assert spec.rule_id in user_prompt
    assert spec.requirement in user_prompt
    assert all(element in user_prompt for element in spec.elements)
    assert [chunk.text for chunk in batch.chunks] == [
        "Сравнение методов локальной проверки",
        "Критерии воспроизводимости",
    ]
    assert all(chunk.chunk_id.startswith("heading:") for chunk in batch.chunks)
    assert SECRET_BODY not in user_prompt
    assert "Ещё один синтетический текст." not in user_prompt


@pytest.mark.parametrize(
    ("status", "state"),
    (("pass", "present"), ("warn", "weak"), ("warn", "absent")),
)
def test_str05_complete_partial_and_missing_element_outcomes(
    status: str,
    state: str,
) -> None:
    payload = _valid_payload(status=status, state=state)
    if state == "absent":
        for element in payload["elements"]:  # type: ignore[index]
            element["evidence"] = []
        payload["evidence"] = []

    finding = (
        SemanticEngine(QueueProvider([payload])).run(_heading_bundle(), (RULE_ID,)).findings[0]
    )

    assert finding.status.value == status
    assert finding.diagnostic is None
    assert finding.status.value != "fail"


def test_str05_missing_subsection_is_diagnostic_without_provider_call() -> None:
    provider = QueueProvider([])
    bundle = make_bundle(
        (("Обзор научно-технической информации", "Только раздел первого уровня."),)
    )

    finding = SemanticEngine(provider).run(bundle, (RULE_ID,)).findings[0]

    assert finding.status is SemanticStatus.NOT_APPLICABLE
    assert finding.diagnostic is DiagnosticCode.SECTION_MISSING
    assert provider.calls == []


def test_str05_exact_heading_quote_is_verified() -> None:
    finding = (
        SemanticEngine(QueueProvider([_valid_payload()]))
        .run(_heading_bundle(), (RULE_ID,))
        .findings[0]
    )

    assert finding.status is SemanticStatus.PASS
    assert finding.evidence
    assert all(item.locator.startswith("sha256:") for item in finding.evidence)


@pytest.mark.parametrize("mode", ("fabricated", "wrong_chunk"))
def test_str05_fabricated_quote_and_wrong_chunk_are_removed(mode: str) -> None:
    quote = "полностью выдуманный заголовок" if mode == "fabricated" else GOLDEN["quote"]
    chunk_id = GOLDEN["chunk_id"] if mode == "fabricated" else "другой:heading"
    payload = response_payload(
        RULE_ID,
        RULE_SPECS[RULE_ID].elements,
        quote=quote,
        chunk_id=chunk_id,
    )

    report = SemanticEngine(QueueProvider([payload, payload])).run(_heading_bundle(), (RULE_ID,))
    finding = report.findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.INVALID_EVIDENCE
    assert finding.evidence == ()
    assert report.batches[0].attempts == 2


@pytest.mark.parametrize("mode", ("duplicate_element", "missing_element", "unknown_field", "fail"))
def test_str05_strict_schema_rejects_invalid_outputs(mode: str) -> None:
    payload = _valid_payload()
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

    finding = SemanticEngine(provider).run(_heading_bundle(), (RULE_ID,)).findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.INVALID_SCHEMA
    assert len(provider.calls) == 2


def test_str05_invalid_json_uses_one_repair_attempt() -> None:
    provider = QueueProvider(["{invalid-json", _valid_payload()])

    report = SemanticEngine(provider).run(_heading_bundle(), (RULE_ID,))

    assert report.findings[0].status is SemanticStatus.PASS
    assert report.batches[0].attempts == 2
    assert len(provider.calls[1]) == 3


@pytest.mark.parametrize(
    ("error", "diagnostic"),
    (
        (LlmUnavailableError("synthetic provider unavailable"), DiagnosticCode.PROVIDER_ERROR),
        (LlmUnavailableError("synthetic request timed out"), DiagnosticCode.PROVIDER_TIMEOUT),
    ),
)
def test_str05_provider_failures_remain_advisory(
    error: Exception,
    diagnostic: DiagnosticCode,
) -> None:
    finding = SemanticEngine(QueueProvider([error])).run(_heading_bundle(), (RULE_ID,)).findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is diagnostic


def test_str05_disabled_provider_is_offline_advisory() -> None:
    finding = SemanticEngine(DisabledProvider()).run(_heading_bundle(), (RULE_ID,)).findings[0]

    assert finding.status is SemanticStatus.UNVERIFIABLE
    assert finding.diagnostic is DiagnosticCode.PROVIDER_DISABLED


def test_str05_unicode_long_document_still_exposes_only_heading() -> None:
    body = SECRET_BODY + " ".join(f"Ёлка café Δ {index}." for index in range(1000))
    bundle = make_bundle(
        (
            ("Обзор научно-технической информации", "Синтетический обзор."),
            (HEADING, body),
        ),
        levels=(1, 2),
    )

    report = SemanticEngine(QueueProvider([_valid_payload()])).run(bundle, (RULE_ID,))

    assert report.findings[0].status is SemanticStatus.PASS
    assert report.batches[0].chunk_ids == (GOLDEN["chunk_id"],)
    assert report.batches[0].token_usage.usage_source == "local_deterministic_estimate"
    assert body not in report.batches[0].model_dump_json()


def test_batch3_findings_are_sorted_text_safe_and_never_fail() -> None:
    report = SemanticEngine(QueueProvider([_valid_payload()])).run(
        _heading_bundle(),
        (RULE_ID, "REV-02"),
    )

    assert [item.rule_id for item in report.findings] == ["REV-02", RULE_ID]
    assert [item.rule_id for item in report.batches] == [RULE_ID]
    assert all(item.status.value != "fail" for item in report.findings)
    audit_json = report.batches[0].model_dump_json()
    assert "local_deterministic_estimate" in audit_json
    assert SECRET_BODY not in audit_json
    assert HEADING not in audit_json
    assert "Критерии воспроизводимости" not in audit_json
