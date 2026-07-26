from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from normocontrol.evaluation.semantic import build_synthetic_bundle, load_semantic_corpus
from normocontrol.llm.base import AdvisoryStatus, ChatMessage, LlmResult, StrictModel
from normocontrol.llm.config import load_llm_config
from normocontrol.llm.disabled import DisabledProvider
from normocontrol.llm.ollama import OllamaProvider
from normocontrol.llm.yandex import YandexProvider
from normocontrol.semantic.batching import BatchPlanner
from normocontrol.semantic.engine import RULE_SPECS, SemanticEngine
from normocontrol.semantic.schemas import (
    ElementState,
    EvidenceQuote,
    SemanticResponse,
    SemanticStatus,
    SupportedElementAssessment,
)


class ContractAnswer(StrictModel):
    status: str
    note: str


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_three_providers_share_one_non_blocking_domain_contract() -> None:
    expected = ContractAnswer(status="info", note="synthetic")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/api/chat":
            assert body["think"] is False
            assert body["format"]["additionalProperties"] is False
            assert body["options"]["num_ctx"] == 8192
            return httpx.Response(
                200,
                json={
                    "model": "contract-model",
                    "done": True,
                    "done_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": expected.model_dump_json(),
                        "thinking": "",
                    },
                },
                request=request,
            )
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "id": "contract",
                "object": "chat.completion",
                "created": 1,
                "model": "contract-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": expected.model_dump_json(),
                            "refusal": None,
                        },
                    }
                ],
            },
            request=request,
        )

    ollama = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama", "LLM_MODEL": "contract-model"}),
        http_client=client(handler),
    )
    yandex = YandexProvider(
        load_llm_config(
            {
                "LLM_PROVIDER": "yandex",
                "LLM_MODEL": "contract-model",
                "LLM_API_KEY": "contract-secret",
                "ALLOW_CLOUD_DATA": "true",
            }
        ),
        http_client=client(handler),
    )
    disabled = DisabledProvider()
    messages = (ChatMessage(role="user", content="synthetic"),)

    results = [
        provider.complete(messages, ContractAnswer) for provider in (ollama, yandex, disabled)
    ]

    for result in results:
        assert LlmResult[ContractAnswer].model_validate(result.model_dump()) == result
    assert results[0].data == expected
    assert results[1].data == expected
    assert results[2].advisory is not None
    assert results[2].advisory.status is AdvisoryStatus.SKIPPED


@pytest.mark.parametrize(
    "rule_id",
    (
        "ALG-01",
        "ALG-03",
        "ANN-01",
        "ARC-01",
        "ARC-02",
        "GEN-02",
        "IMP-01",
        "MTH-02",
        "MTH-03",
        "RES-01",
        "REV-05",
        "REV-06",
        "SSA-04",
        "STR-05",
        "TSK-02",
    ),
)
def test_ollama_contract_repairs_invalid_json_then_verifies_exact_evidence(
    rule_id: str,
) -> None:
    corpus = load_semantic_corpus(Path("tests/fixtures/semantic/corpus.json"))
    fixture = next(item for item in corpus.fixtures if item.id == "positive")
    expectation = next(item for item in fixture.expectations if item.rule_id == rule_id)
    bundle = build_synthetic_bundle(fixture)
    quote = expectation.evidence_quote
    assert quote is not None
    owner = next(
        chunk
        for chunk in BatchPlanner().plan(bundle, RULE_SPECS[rule_id]).chunks
        if quote in chunk.text
    )
    evidence = (EvidenceQuote(chunk_id=owner.chunk_id, quote=quote),)
    valid = SemanticResponse(
        rule_id=rule_id,
        status=SemanticStatus.PASS,
        confidence=0.95,
        summary="Синтетический ответ подтверждён точной цитатой.",
        evidence=evidence,
        elements=tuple(
            SupportedElementAssessment(
                element=element,
                state=ElementState.PRESENT,
                evidence=evidence,
            )
            for element in RULE_SPECS[rule_id].elements
        ),
    )
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content)
        requests.append(body)
        response_format = body["format"]
        assert isinstance(response_format, dict)
        assert response_format["additionalProperties"] is False
        content = '{"r":' if len(requests) == 1 else valid.model_dump_json(by_alias=True)
        return httpx.Response(
            200,
            json={
                "model": "contract-model",
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": content, "thinking": ""},
            },
            request=request,
        )

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama", "LLM_MODEL": "contract-model"}),
        http_client=client(handler),
    )

    report = SemanticEngine(provider, model_id="contract-model").run(bundle, (rule_id,))

    assert report.findings[0].status is SemanticStatus.PASS
    assert report.findings[0].evidence
    if quote == owner.text:
        assert report.findings[0].evidence[0].locator == owner.quote_locator
    else:
        assert report.findings[0].evidence[0].locator != owner.quote_locator
    assert report.batches[0].attempts == 2
    assert len(requests[1]["messages"]) == 3
