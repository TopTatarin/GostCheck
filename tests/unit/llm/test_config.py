from __future__ import annotations

import pytest

from normocontrol.errors import ConfigurationError
from normocontrol.llm.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    YANDEX_BASE_URL,
    ProviderName,
    load_llm_config,
)


def test_ollama_defaults_and_empty_placeholder_key() -> None:
    config = load_llm_config({"LLM_PROVIDER": "ollama", "LLM_API_KEY": ""})

    assert config.provider is ProviderName.OLLAMA
    assert config.base_url == OLLAMA_BASE_URL
    assert config.model == OLLAMA_MODEL
    assert config.api_key.get_secret_value() == "ollama"
    assert config.max_concurrency == 1


def test_cli_override_wins_conflicting_environment_and_no_llm_wins_all() -> None:
    environment = {"LLM_PROVIDER": "ollama", "LLM_MODEL": "environment-model"}

    cli = load_llm_config(
        environment,
        provider_override="ollama",
        model_override="cli-model",
    )
    disabled = load_llm_config(environment, provider_override="yandex", no_llm=True)

    assert cli.model == "cli-model"
    assert disabled.provider is ProviderName.DISABLED


def test_yandex_uses_fixed_defaults_and_requires_env_model_key_and_cloud_policy() -> None:
    config = load_llm_config(
        {
            "LLM_PROVIDER": "yandex",
            "LLM_MODEL": "gpt://folder/model/latest",
            "LLM_API_KEY": "unit-secret",
            "ALLOW_CLOUD_DATA": "true",
        }
    )

    assert config.base_url == YANDEX_BASE_URL
    assert config.model == "gpt://folder/model/latest"


@pytest.mark.parametrize(
    "environment",
    [
        {"LLM_PROVIDER": "yandex", "LLM_API_KEY": "key", "ALLOW_CLOUD_DATA": "true"},
        {
            "LLM_PROVIDER": "yandex",
            "LLM_MODEL": "gpt://folder/model",
            "LLM_API_KEY": "",
            "ALLOW_CLOUD_DATA": "true",
        },
        {
            "LLM_PROVIDER": "yandex",
            "LLM_MODEL": "gpt://folder/model",
            "LLM_API_KEY": "key",
            "ALLOW_CLOUD_DATA": "false",
        },
    ],
)
def test_invalid_yandex_configuration_is_sanitized(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError) as captured:
        load_llm_config(environment)

    assert "unit-secret" not in str(captured.value)


def test_yandex_model_uri_cannot_be_overridden_by_cli() -> None:
    with pytest.raises(ConfigurationError, match="through LLM_MODEL"):
        load_llm_config(
            {
                "LLM_PROVIDER": "yandex",
                "LLM_MODEL": "gpt://folder/env",
                "LLM_API_KEY": "key",
                "ALLOW_CLOUD_DATA": "true",
            },
            model_override="gpt://folder/cli",
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [("LLM_TIMEOUT", "zero-ish"), ("LLM_MAX_CONCURRENCY", "many")],
)
def test_numeric_environment_errors_name_the_setting(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError, match=name):
        load_llm_config({"LLM_PROVIDER": "ollama", name: value})
