"""Environment and CLI resolution for LLM providers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from normocontrol.errors import ConfigurationError

OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
OLLAMA_MODEL = "qwen3:8b-q4_K_M"
OLLAMA_NUM_CTX = 8192
OLLAMA_MAX_OUTPUT_TOKENS = 512
YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"


class ProviderName(StrEnum):
    """Supported LLM provider profiles."""

    OLLAMA = "ollama"
    YANDEX = "yandex"
    DISABLED = "disabled"


class LlmConfig(BaseModel):
    """Resolved, immutable provider configuration with a protected API key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName = ProviderName.DISABLED
    base_url: str = ""
    model: str = ""
    api_key: SecretStr = SecretStr("")
    timeout: float = Field(default=60.0, gt=0)
    max_concurrency: int = Field(default=1, ge=1)
    num_ctx: int = Field(default=OLLAMA_NUM_CTX, ge=512, le=131_072)
    max_output_tokens: int = Field(default=OLLAMA_MAX_OUTPUT_TOKENS, ge=1, le=8192)
    allow_cloud_data: bool = False

    @model_validator(mode="after")
    def validate_profile(self) -> LlmConfig:
        if self.provider is ProviderName.DISABLED:
            return self
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LLM_BASE_URL must be an absolute HTTP(S) URL")
        if not self.model.strip():
            raise ValueError("LLM_MODEL is required for the selected provider")
        if self.max_output_tokens >= self.num_ctx:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS must be smaller than LLM_NUM_CTX")
        if self.provider is ProviderName.YANDEX:
            if not self.api_key.get_secret_value().strip():
                raise ValueError("LLM_API_KEY is required for Yandex")
            if not self.allow_cloud_data:
                raise ValueError("Yandex is forbidden unless ALLOW_CLOUD_DATA=true")
        return self


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _parse_float(name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error


def _parse_int(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error


def load_llm_config(
    environ: Mapping[str, str] | None = None,
    *,
    config_values: Mapping[str, object] | None = None,
    provider_override: str | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
    no_llm: bool = False,
) -> LlmConfig:
    """Resolve YAML defaults, environment, and CLI overrides in increasing priority."""
    values = os.environ if environ is None else environ
    configured = {} if config_values is None else config_values
    configured_provider = configured.get("provider", "disabled")
    if not isinstance(configured_provider, str):
        raise ConfigurationError("llm.provider in config must be a string")
    provider_raw = (
        "disabled"
        if no_llm
        else provider_override or values.get("LLM_PROVIDER") or configured_provider
    )
    try:
        provider = ProviderName(provider_raw.strip().casefold())
    except ValueError as error:
        raise ConfigurationError("LLM_PROVIDER must be ollama, yandex, or disabled") from error

    if provider is ProviderName.DISABLED:
        return LlmConfig(provider=provider)

    default_url = OLLAMA_BASE_URL if provider is ProviderName.OLLAMA else YANDEX_BASE_URL
    default_model = OLLAMA_MODEL if provider is ProviderName.OLLAMA else ""
    configured_url = configured.get("base_url")
    configured_model = configured.get("model")
    if configured_url is not None and not isinstance(configured_url, str):
        raise ConfigurationError("llm.base_url in config must be a string or null")
    if configured_model is not None and not isinstance(configured_model, str):
        raise ConfigurationError("llm.model in config must be a string or null")
    configured_cloud = configured.get("allow_cloud_data", False)
    if not isinstance(configured_cloud, bool):
        raise ConfigurationError("llm.allow_cloud_data in config must be true or false")
    raw_key = values.get("LLM_API_KEY", "")
    if provider is ProviderName.OLLAMA and not raw_key.strip():
        raw_key = "ollama"

    cloud_raw = values.get("ALLOW_CLOUD_DATA", values.get("LLM_ALLOW_CLOUD_DATA"))
    allow_cloud_data = (
        configured_cloud if cloud_raw is None else _parse_bool("ALLOW_CLOUD_DATA", cloud_raw)
    )
    payload = {
        "provider": provider,
        "base_url": (
            base_url_override or values.get("LLM_BASE_URL") or configured_url or default_url
        ),
        "model": model_override or values.get("LLM_MODEL") or configured_model or default_model,
        "api_key": SecretStr(raw_key),
        "timeout": _parse_float("LLM_TIMEOUT", values.get("LLM_TIMEOUT", "60")),
        "max_concurrency": _parse_int(
            "LLM_MAX_CONCURRENCY", values.get("LLM_MAX_CONCURRENCY", "1")
        ),
        "num_ctx": _parse_int("LLM_NUM_CTX", values.get("LLM_NUM_CTX", str(OLLAMA_NUM_CTX))),
        "max_output_tokens": _parse_int(
            "LLM_MAX_OUTPUT_TOKENS",
            values.get("LLM_MAX_OUTPUT_TOKENS", str(OLLAMA_MAX_OUTPUT_TOKENS)),
        ),
        "allow_cloud_data": allow_cloud_data,
    }
    try:
        return LlmConfig.model_validate(payload)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
