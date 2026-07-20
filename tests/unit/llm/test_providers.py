from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx
import pytest

from normocontrol.llm.base import (
    AdvisoryStatus,
    ChatMessage,
    LlmResponseError,
    LlmUnavailableError,
    StrictModel,
)
from normocontrol.llm.config import LlmConfig, ProviderName, load_llm_config
from normocontrol.llm.disabled import DisabledProvider
from normocontrol.llm.ollama import OllamaProvider
from normocontrol.llm.openai_provider import OpenAICompatibleProvider
from normocontrol.llm.retry import RetryPolicy
from normocontrol.llm.yandex import YandexProvider


class Answer(StrictModel):
    verdict: str
    score: int


MESSAGES = (ChatMessage(role="user", content="synthetic input"),)
FAST_RETRY = RetryPolicy(max_elapsed=1, max_attempts=4, initial=0, maximum=0)


def completion_payload(
    content: str | None,
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
) -> dict[str, object]:
    return {
        "id": "chatcmpl-unit",
        "object": "chat.completion",
        "created": 1,
        "model": "unit-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
    }


def make_http_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("provider_name", [ProviderName.OLLAMA, ProviderName.YANDEX])
def test_profiles_send_json_schema_and_return_same_typed_response(
    provider_name: ProviderName,
) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=completion_payload('{"verdict":"ok","score":2}'))

    if provider_name is ProviderName.OLLAMA:
        config = load_llm_config({"LLM_PROVIDER": "ollama", "LLM_MODEL": "unit-model"})
        provider: OpenAICompatibleProvider = OllamaProvider(
            config, http_client=make_http_client(handler)
        )
    else:
        config = load_llm_config(
            {
                "LLM_PROVIDER": "yandex",
                "LLM_MODEL": "unit-model",
                "LLM_API_KEY": "yandex-unit-secret",
                "ALLOW_CLOUD_DATA": "true",
            }
        )
        provider = YandexProvider(config, http_client=make_http_client(handler))

    result = provider.complete(MESSAGES, Answer)

    assert result.data == Answer(verdict="ok", score=2)
    assert captured[0]["temperature"] == 0
    assert captured[0]["stream"] is False
    response_format = captured[0]["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    if provider_name is ProviderName.OLLAMA:
        assert captured[0]["reasoning_effort"] == "none"


def test_markdown_fenced_json_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=completion_payload('```json\n{"verdict":"ok","score":3}\n```'),
            request=request,
        )

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama"}),
        http_client=make_http_client(handler),
    )

    assert provider.request(MESSAGES, Answer).score == 3


@pytest.mark.parametrize(
    ("content", "finish_reason", "refusal", "expected"),
    [
        (None, "stop", None, "content is null"),
        ('{"verdict":"ok"', "length", None, "token limit"),
        ('{"verdict":"ok","score":1,"extra":true}', "stop", None, "JSON schema"),
        ("not-json", "stop", None, "JSON schema"),
        (None, "stop", "policy refusal", "refused"),
    ],
)
def test_invalid_model_outputs_are_typed_and_non_blocking(
    content: str | None,
    finish_reason: str,
    refusal: str | None,
    expected: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=completion_payload(
                content,
                finish_reason=finish_reason,
                refusal=refusal,
            ),
            request=request,
        )

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama"}),
        http_client=make_http_client(handler),
    )

    with pytest.raises(LlmResponseError, match=expected):
        provider.request(MESSAGES, Answer)
    result = provider.complete(MESSAGES, Answer)
    assert result.data is None
    assert result.advisory is not None
    assert result.advisory.status is AdvisoryStatus.UNVERIFIABLE


def test_stream_response_is_rejected_for_non_stream_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"choices": []}\n\n',
            request=request,
        )

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama"}),
        http_client=make_http_client(handler),
    )

    result = provider.complete(MESSAGES, Answer)

    assert result.advisory is not None
    assert result.advisory.status is AdvisoryStatus.UNVERIFIABLE


def test_disabled_provider_returns_skipped_without_io() -> None:
    provider = DisabledProvider()

    probe = provider.health_check()
    result = provider.complete(MESSAGES, Answer)

    assert probe.available is False
    assert result.data is None
    assert result.advisory is not None
    assert result.advisory.status is AdvisoryStatus.SKIPPED


def test_models_probe_reports_missing_model_and_daemon_off() -> None:
    def models_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "another-model", "object": "model"}]},
            request=request,
        )

    configured = load_llm_config({"LLM_PROVIDER": "ollama", "LLM_MODEL": "missing"})
    missing = OllamaProvider(
        configured,
        http_client=make_http_client(models_handler),
    ).health_check()

    def daemon_off(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("daemon is off", request=request)

    offline = OllamaProvider(
        configured,
        http_client=make_http_client(daemon_off),
        retry_policy=FAST_RETRY,
        sleep=lambda _: None,
    ).health_check()

    assert missing.available is True
    assert missing.model_available is False
    assert offline.available is False
    assert "unavailable" in offline.detail


def test_timeout_retries_and_returns_unverifiable() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("unit timeout", request=request)

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama"}),
        http_client=make_http_client(handler),
        retry_policy=FAST_RETRY,
        sleep=lambda _: None,
    )

    result = provider.complete(MESSAGES, Answer)

    assert attempts == 4
    assert result.advisory is not None
    assert result.advisory.status is AdvisoryStatus.UNVERIFIABLE


@pytest.mark.parametrize("status", [429, 500])
def test_transient_http_status_then_success(status: int) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            headers = {"Retry-After": "0.25"} if status == 429 else {}
            return httpx.Response(status, headers=headers, json={"error": "transient"})
        return httpx.Response(200, json=completion_payload('{"verdict":"ok","score":5}'))

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama"}),
        http_client=make_http_client(handler),
        retry_policy=FAST_RETRY,
        sleep=sleeps.append,
    )

    answer = provider.request(MESSAGES, Answer)

    assert answer.score == 5
    assert attempts == 2
    if status == 429:
        assert sleeps == [0.25]


def test_401_is_not_retried_and_secret_never_reaches_error_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0
    secret = "yandex-super-secret-unit-key"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": f"rejected {secret}"})

    config = LlmConfig(
        provider=ProviderName.YANDEX,
        base_url="https://ai.api.cloud.yandex.net/v1",
        model="gpt://folder/model",
        api_key=secret,
        allow_cloud_data=True,
    )
    provider = YandexProvider(
        config,
        http_client=make_http_client(handler),
        retry_policy=FAST_RETRY,
        sleep=lambda _: None,
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(LlmUnavailableError) as captured:
        provider.request(MESSAGES, Answer)

    assert attempts == 1
    snapshot = f"{captured.value!r}\n{caplog.text}\n{config!r}"
    assert secret not in snapshot


def test_no_gpu_configuration_is_required_for_local_cpu_fallback() -> None:
    config = load_llm_config({"LLM_PROVIDER": "ollama"})

    assert config.provider is ProviderName.OLLAMA
    assert "GPU" not in config.model_dump()
