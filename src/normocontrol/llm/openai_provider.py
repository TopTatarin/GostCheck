"""Shared OpenAI-compatible client with strict schema parsing."""

from __future__ import annotations

import re
from collections.abc import Callable
from json import JSONDecodeError
from threading import BoundedSemaphore
from typing import Any, cast

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
    Stream,
)
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from normocontrol.llm.base import (
    ChatMessage,
    LlmProvider,
    LlmRefusalError,
    LlmResponseError,
    LlmUnavailableError,
    ProbeResult,
)
from normocontrol.llm.config import LlmConfig
from normocontrol.llm.retry import RetryPolicy, call_with_retry

_MARKDOWN_JSON = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.IGNORECASE | re.DOTALL)


class OpenAICompatibleProvider(LlmProvider):
    """Base implementation for non-streaming OpenAI-compatible providers."""

    def __init__(
        self,
        config: LlmConfig,
        *,
        http_client: httpx.Client | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self._client = OpenAI(
            api_key=config.api_key.get_secret_value(),
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=0,
            http_client=http_client,
        )
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._semaphore = BoundedSemaphore(config.max_concurrency)

    @property
    def name(self) -> str:
        return self.config.provider.value

    def _extra_body(self) -> dict[str, object] | None:
        return None

    def health_check(self) -> ProbeResult:
        """Probe ``/models`` and distinguish daemon from model availability."""
        try:
            with self._semaphore:
                models = call_with_retry(
                    self._client.models.list,
                    policy=self._retry_policy,
                    sleep=self._sleep,
                )
        except OpenAIError as error:
            return ProbeResult(
                provider=self.name,
                available=False,
                detail=self._safe_error_detail(error),
            )
        try:
            installed = {item.id for item in models.data}
        except (AttributeError, TypeError):
            return ProbeResult(
                provider=self.name,
                available=False,
                detail=f"{self.name} returned an invalid capability response",
            )
        model_available = self.config.model in installed
        return ProbeResult(
            provider=self.name,
            available=True,
            model_available=model_available,
            detail="ready" if model_available else "configured model is not available",
        )

    def request[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> ResponseT:
        """Request one non-streaming completion and validate its JSON payload."""
        message_params = [
            cast(ChatCompletionMessageParam, message.model_dump()) for message in messages
        ]
        response_format = cast(
            ResponseFormatJSONSchema,
            {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
        )

        def invoke() -> Any:
            return self._client.chat.completions.create(
                model=self.config.model,
                messages=message_params,
                temperature=0,
                stream=False,
                response_format=response_format,
                extra_body=self._extra_body(),
            )

        try:
            with self._semaphore:
                response = call_with_retry(
                    invoke,
                    policy=self._retry_policy,
                    sleep=self._sleep,
                )
        except (APIConnectionError, APITimeoutError) as error:
            raise LlmUnavailableError(self._safe_error_detail(error)) from None
        except APIStatusError as error:
            status_message = f"{self.name} request failed with HTTP {error.status_code}"
            if error.status_code in {400, 422}:
                raise LlmResponseError(status_message) from None
            raise LlmUnavailableError(status_message) from None
        except OpenAIError:
            raise LlmResponseError(f"{self.name} returned an invalid API response") from None

        if isinstance(response, Stream):
            raise LlmResponseError(f"{self.name} returned a stream for a non-stream request")
        if isinstance(response, str) and response.lstrip().startswith("data:"):
            raise LlmResponseError(f"{self.name} returned a stream for a non-stream request")
        if not hasattr(response, "choices"):
            raise LlmResponseError(f"{self.name} returned an invalid API response")
        choices = response.choices
        if not choices:
            raise LlmResponseError(f"{self.name} response has no choices")
        choice = choices[0]
        assistant_message = getattr(choice, "message", None)
        if assistant_message is None:
            raise LlmResponseError(f"{self.name} response has no assistant message")
        refusal = getattr(assistant_message, "refusal", None)
        if refusal:
            raise LlmRefusalError(f"{self.name} refused the request")
        if choice.finish_reason == "length":
            raise LlmResponseError(f"{self.name} response was truncated by the token limit")
        content = getattr(assistant_message, "content", None)
        if content is None:
            raise LlmResponseError(f"{self.name} response content is null")
        cleaned = content.strip()
        fenced = _MARKDOWN_JSON.fullmatch(cleaned)
        if fenced is not None:
            cleaned = fenced.group(1)
        try:
            return response_model.model_validate_json(cleaned)
        except (JSONDecodeError, ValidationError, ValueError):
            raise LlmResponseError(
                f"{self.name} response does not match the requested JSON schema"
            ) from None

    def _safe_error_detail(self, error: OpenAIError) -> str:
        if isinstance(error, APITimeoutError):
            return f"{self.name} request timed out"
        if isinstance(error, APIConnectionError):
            return f"{self.name} endpoint is unavailable"
        if isinstance(error, APIStatusError):
            return f"{self.name} request failed with HTTP {error.status_code}"
        return f"{self.name} endpoint is unavailable"
