"""Yandex AI Studio OpenAI-compatible provider."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from normocontrol.llm.config import LlmConfig, ProviderName
from normocontrol.llm.openai_provider import OpenAICompatibleProvider
from normocontrol.llm.retry import RetryPolicy


class YandexProvider(OpenAICompatibleProvider):
    """Cloud profile enabled only after explicit data-policy authorization."""

    def __init__(
        self,
        config: LlmConfig,
        *,
        http_client: httpx.Client | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if config.provider is not ProviderName.YANDEX:
            raise ValueError("YandexProvider requires provider=yandex")
        if not config.allow_cloud_data:
            raise ValueError("YandexProvider requires allow_cloud_data=true")
        super().__init__(
            config,
            http_client=http_client,
            retry_policy=retry_policy,
            sleep=sleep,
        )
