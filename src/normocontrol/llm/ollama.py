"""Local Ollama provider using its OpenAI-compatible endpoint."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from normocontrol.llm.config import LlmConfig, ProviderName
from normocontrol.llm.openai_provider import OpenAICompatibleProvider
from normocontrol.llm.retry import RetryPolicy


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
        super().__init__(
            config,
            http_client=http_client,
            retry_policy=retry_policy,
            sleep=sleep,
        )

    def _extra_body(self) -> dict[str, object]:
        # openai 1.x does not type Ollama's documented literal ``none``;
        # extra_body still merges it into the top-level JSON request.
        return {"reasoning_effort": "none"}
