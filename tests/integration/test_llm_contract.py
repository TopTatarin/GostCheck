from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from normocontrol.llm.base import AdvisoryStatus, ChatMessage, LlmResult, StrictModel
from normocontrol.llm.config import load_llm_config
from normocontrol.llm.disabled import DisabledProvider
from normocontrol.llm.ollama import OllamaProvider
from normocontrol.llm.yandex import YandexProvider


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
