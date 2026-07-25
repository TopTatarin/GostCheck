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
from normocontrol.llm.ollama import OllamaProvider, native_api_url
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


def ollama_payload(
    content: str | None,
    *,
    done_reason: str = "stop",
    thinking: str | None = None,
) -> dict[str, object]:
    return {
        "model": "unit-model",
        "done": True,
        "done_reason": done_reason,
        "message": {
            "role": "assistant",
            "content": content,
            "thinking": thinking,
        },
    }


def make_http_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_native_url_mapping_preserves_explicit_ipv6_override() -> None:
    assert native_api_url("http://[::1]:11434/v1/", "/api/chat") == "http://[::1]:11434/api/chat"


@pytest.mark.parametrize("provider_name", [ProviderName.OLLAMA, ProviderName.YANDEX])
def test_profiles_send_json_schema_and_return_same_typed_response(
    provider_name: ProviderName,
) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        if provider_name is ProviderName.OLLAMA:
            return httpx.Response(
                200,
                json=ollama_payload('{"verdict":"ok","score":2}'),
                request=request,
            )
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
    assert captured[0]["stream"] is False
    if provider_name is ProviderName.OLLAMA:
        assert captured[0]["think"] is False
        schema = captured[0]["format"]
        assert isinstance(schema, dict)
        assert schema["additionalProperties"] is False
        options = captured[0]["options"]
        assert isinstance(options, dict)
        assert options == {
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 512,
        }
    else:
        assert captured[0]["temperature"] == 0
        response_format = captured[0]["response_format"]
        assert isinstance(response_format, dict)
        assert response_format["type"] == "json_schema"


def test_markdown_fenced_json_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=ollama_payload('```json\n{"verdict":"ok","score":3}\n```'),
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
            json=(
                completion_payload(content, finish_reason=finish_reason, refusal=refusal)
                if refusal
                else ollama_payload(
                    content,
                    done_reason="length" if finish_reason == "length" else finish_reason,
                )
            ),
            request=request,
        )

    if refusal:
        provider: OpenAICompatibleProvider = YandexProvider(
            load_llm_config(
                {
                    "LLM_PROVIDER": "yandex",
                    "LLM_MODEL": "unit-model",
                    "LLM_API_KEY": "unit-key",
                    "ALLOW_CLOUD_DATA": "true",
                }
            ),
            http_client=make_http_client(handler),
        )
    else:
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


def test_health_probe_distinguishes_schema_capability_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": "unit-model", "object": "model"}]},
                request=request,
            )
        return httpx.Response(400, json={"error": "format unsupported"}, request=request)

    probe = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama", "LLM_MODEL": "unit-model"}),
        http_client=make_http_client(handler),
    ).health_check()

    assert probe.available is False
    assert probe.model_available is True
    assert probe.schema_available is False
    assert "schema capability" in probe.detail


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
        return httpx.Response(
            200,
            json=ollama_payload('{"verdict":"ok","score":5}'),
            request=request,
        )

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


def test_ollama_auth_4xx_is_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "denied"}, request=request)

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama"}),
        http_client=make_http_client(handler),
        retry_policy=FAST_RETRY,
        sleep=lambda _: None,
    )

    with pytest.raises(LlmUnavailableError, match="HTTP 401"):
        provider.request(MESSAGES, Answer)

    assert attempts == 1


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


def test_reasoning_is_ignored_when_content_has_valid_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=ollama_payload(
                '{"verdict":"ok","score":7}',
                thinking="private reasoning must not become content",
            ),
            request=request,
        )

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama"}),
        http_client=make_http_client(handler),
    )

    assert provider.request(MESSAGES, Answer).score == 7


def test_invalid_response_and_config_repr_do_not_expose_secret_or_prompt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "ollama-unit-secret"
    private_prompt = "synthetic-private-prompt"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=ollama_payload(f"```json\n{secret}\n```"),
            request=request,
        )

    config = load_llm_config(
        {
            "LLM_PROVIDER": "ollama",
            "LLM_API_KEY": secret,
        }
    )
    provider = OllamaProvider(config, http_client=make_http_client(handler))
    messages = (ChatMessage(role="user", content=private_prompt),)

    with caplog.at_level(logging.DEBUG), pytest.raises(LlmResponseError) as captured:
        provider.request(messages, Answer)

    snapshot = f"{captured.value!r}\n{caplog.text}\n{config!r}"
    assert secret not in snapshot
    assert private_prompt not in snapshot


def test_default_ollama_client_ignores_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://[::1]:1")
    provider = OllamaProvider(load_llm_config({"LLM_PROVIDER": "ollama"}))

    assert provider._ollama_client._trust_env is False
    provider._ollama_client.close()
