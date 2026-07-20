"""Environment and CLI resolution for LLM providers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from normocontrol.errors import ConfigurationError

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "qwen3:8b-q4_K_M"
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
    provider_override: str | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
    no_llm: bool = False,
) -> LlmConfig:
    """Resolve environment plus CLI overrides; explicit CLI values take precedence."""
    values = os.environ if environ is None else environ
    provider_raw = (
        "disabled" if no_llm else provider_override or values.get("LLM_PROVIDER", "disabled")
    )
    try:
        provider = ProviderName(provider_raw.strip().casefold())
    except ValueError as error:
        raise ConfigurationError("LLM_PROVIDER must be ollama, yandex, or disabled") from error

    if provider is ProviderName.DISABLED:
        return LlmConfig(provider=provider)

    if provider is ProviderName.YANDEX and model_override is not None:
        raise ConfigurationError("Yandex model URI must be supplied through LLM_MODEL")

    default_url = OLLAMA_BASE_URL if provider is ProviderName.OLLAMA else YANDEX_BASE_URL
    default_model = OLLAMA_MODEL if provider is ProviderName.OLLAMA else ""
    raw_key = values.get("LLM_API_KEY", "")
    if provider is ProviderName.OLLAMA and not raw_key.strip():
        raw_key = "ollama"

    payload = {
        "provider": provider,
        "base_url": base_url_override or values.get("LLM_BASE_URL", default_url),
        "model": model_override or values.get("LLM_MODEL", default_model),
        "api_key": SecretStr(raw_key),
        "timeout": _parse_float("LLM_TIMEOUT", values.get("LLM_TIMEOUT", "60")),
        "max_concurrency": _parse_int(
            "LLM_MAX_CONCURRENCY", values.get("LLM_MAX_CONCURRENCY", "1")
        ),
        "allow_cloud_data": _parse_bool(
            "ALLOW_CLOUD_DATA",
            values.get("ALLOW_CLOUD_DATA", values.get("LLM_ALLOW_CLOUD_DATA", "false")),
        ),
    }
    try:
        return LlmConfig.model_validate(payload)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
