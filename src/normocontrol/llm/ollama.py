"""Local Ollama provider using its OpenAI-compatible endpoint."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from normocontrol.llm.base import (
    ChatMessage,
    LlmResponseError,
    LlmUnavailableError,
    ProbeResult,
    StrictModel,
)
from normocontrol.llm.config import LlmConfig, ProviderName
from normocontrol.llm.openai_provider import OpenAICompatibleProvider
from normocontrol.llm.retry import RetryPolicy, call_with_retry


class _SchemaProbe(StrictModel):
    status: Literal["ok"]


def native_api_url(base_url: str, endpoint: str) -> str:
    """Map the public OpenAI-compatible base URL to an Ollama native endpoint."""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/{endpoint.lstrip('/')}"


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama profile; the daemon selects GPU or CPU execution automatically."""

    def __init__(
        self,
        config: LlmConfig,
        *,
        http_client: httpx.Client | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if config.provider is not ProviderName.OLLAMA:
            raise ValueError("OllamaProvider requires provider=ollama")
        self._ollama_client = http_client or httpx.Client(trust_env=False)
        super().__init__(
            config,
            http_client=self._ollama_client,
            retry_policy=retry_policy,
            sleep=sleep,
        )

    def health_check(self) -> ProbeResult:
        """Distinguish daemon, model, and strict-schema capability failures."""
        model_probe = super().health_check()
        if not model_probe.available or not model_probe.model_available:
            return model_probe
        try:
            self.request(
                (ChatMessage(role="user", content='Return exactly {"status":"ok"}.'),),
                _SchemaProbe,
            )
        except LlmUnavailableError as error:
            detail = str(error)
            model_available = detail != "configured model is not available"
            return ProbeResult(
                provider=self.name,
                available=False,
                model_available=model_available,
                schema_available=False,
                detail=detail,
            )
        except LlmResponseError:
            return ProbeResult(
                provider=self.name,
                available=False,
                model_available=True,
                schema_available=False,
                detail="strict JSON schema capability is unavailable",
            )
        return ProbeResult(
            provider=self.name,
            available=True,
            model_available=True,
            schema_available=True,
            detail="ready (strict JSON schema available)",
        )

    def request[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> ResponseT:
        """Use native chat so Qwen thinking and context limits are honored."""
        body = self._request_body(messages, response_model)

        def invoke() -> httpx.Response:
            response = self._ollama_client.post(
                native_api_url(self.config.base_url, "/api/chat"),
                json=body,
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            return response

        try:
            with self._semaphore:
                response = call_with_retry(
                    invoke,
                    policy=self._retry_policy,
                    sleep=self._sleep,
                )
        except httpx.TimeoutException:
            raise LlmUnavailableError(f"{self.name} request timed out") from None
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            if status_code in {400, 422}:
                raise LlmResponseError(
                    f"{self.name} request failed with HTTP {status_code}"
                ) from None
            if status_code == 404:
                raise LlmUnavailableError("configured model is not available") from None
            raise LlmUnavailableError(
                f"{self.name} request failed with HTTP {status_code}"
            ) from None
        except httpx.RequestError:
            raise LlmUnavailableError(f"{self.name} endpoint is unavailable") from None

        try:
            payload: Any = response.json()
        except ValueError:
            raise LlmResponseError(f"{self.name} returned an invalid API response") from None
        if not isinstance(payload, dict):
            raise LlmResponseError(f"{self.name} returned an invalid API response")
        if payload.get("done_reason") == "length":
            raise LlmResponseError(f"{self.name} response was truncated by the token limit")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise LlmResponseError(f"{self.name} response has no assistant message")
        content = message.get("content")
        if not isinstance(content, str):
            raise LlmResponseError(f"{self.name} response content is null")
        return self._validate_content(content, response_model)

    def _request_body(
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[BaseModel],
    ) -> dict[str, object]:
        return {
            "model": self.config.model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
            "think": False,
            "format": response_model.model_json_schema(),
            "options": {
                "temperature": 0,
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.max_output_tokens,
            },
        }
