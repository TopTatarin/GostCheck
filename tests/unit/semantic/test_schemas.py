from __future__ import annotations

import pytest
from pydantic import ValidationError

from normocontrol.semantic.schemas import SemanticResponse, TokenUsage

from .helpers import response_payload


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"status": "fail"}, "status"),
        ({"confidence": "0.9"}, "valid number"),
        ({"rule_id": "XXX-99"}, "not implemented"),
        ({"summary": "<html>answer</html>"}, "HTML"),
        ({"summary": "```json"}, "markdown"),
        ({"chain_of_thought": "secret"}, "Extra inputs"),
    ],
)
def test_response_schema_rejects_unsafe_or_unknown_output(
    change: dict[str, object], message: str
) -> None:
    payload = response_payload("TSK-01", (), status="not_applicable")
    payload.update(change)

    with pytest.raises(ValidationError, match=message):
        SemanticResponse.model_validate(payload)


def test_quote_longer_than_ten_words_is_rejected() -> None:
    payload = response_payload(
        "TSK-01",
        (),
        status="not_applicable",
        quote="а б в г д е ж з и к л",
        chunk_id="task:1",
    )

    with pytest.raises(ValidationError, match="at most 10 words"):
        SemanticResponse.model_validate(payload)


def test_model_cannot_invent_an_evidence_locator() -> None:
    payload = response_payload(
        "TSK-01",
        (),
        status="not_applicable",
        quote="точная цитата",
        chunk_id="task:1",
    )
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    evidence[0]["locator"] = "invented:1"

    with pytest.raises(ValidationError, match="Extra inputs"):
        SemanticResponse.model_validate(payload)


def test_compact_llm_wire_aliases_preserve_public_field_names() -> None:
    public_payload = response_payload(
        "TSK-01",
        (),
        status="not_applicable",
    )
    response = SemanticResponse.model_validate(public_payload)

    compact = response.model_dump(mode="json", by_alias=True)
    restored = SemanticResponse.model_validate(compact)

    assert set(compact) == {"r", "s", "c", "m", "q", "e"}
    assert restored == response
    assert set(response.model_dump()) == {
        "rule_id",
        "status",
        "confidence",
        "summary",
        "evidence",
        "elements",
    }
    assert set(SemanticResponse.model_json_schema()["properties"]) == {
        "r",
        "s",
        "c",
        "m",
        "q",
        "e",
    }


def test_token_usage_is_explicitly_a_local_estimate_and_strict() -> None:
    usage = TokenUsage(input_tokens=10, output_tokens=3, total_tokens=13)

    assert usage.usage_source == "local_deterministic_estimate"
    with pytest.raises(ValidationError, match="Input should be 'local_deterministic_estimate'"):
        TokenUsage(
            input_tokens=10,
            output_tokens=3,
            total_tokens=13,
            usage_source="server_billing",  # type: ignore[arg-type]
        )
