from __future__ import annotations

import pytest
from pydantic import ValidationError

from normocontrol.semantic.schemas import SemanticResponse

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
        quote="один два три четыре пять шесть семь восемь девять десять одиннадцать",
        chunk_id="task:1",
    )

    with pytest.raises(ValidationError, match="at most 10 words"):
        SemanticResponse.model_validate(payload)
