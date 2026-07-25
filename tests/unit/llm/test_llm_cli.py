from __future__ import annotations

import pytest
from typer.testing import CliRunner

import normocontrol.cli as cli_module
from normocontrol.cli import app
from normocontrol.llm.base import ProbeResult

runner = CliRunner()


def test_llm_doctor_disabled_is_deterministic_and_offline() -> None:
    result = runner.invoke(app, ["llm", "doctor", "--provider", "disabled"])

    assert result.exit_code == 0
    assert "provider=disabled" in result.stdout
    assert "status=SKIPPED" in result.stdout


def test_global_no_llm_wins_conflicting_cli_and_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    result = runner.invoke(
        app,
        ["--no-llm", "llm", "doctor", "--provider", "yandex"],
    )

    assert result.exit_code == 0
    assert "provider=disabled" in result.stdout
    assert "status=SKIPPED" in result.stdout


@pytest.mark.parametrize(
    ("probe", "expected_detail"),
    [
        (
            ProbeResult(
                provider="ollama",
                available=False,
                detail="ollama endpoint is unavailable",
            ),
            "endpoint is unavailable",
        ),
        (
            ProbeResult(
                provider="ollama",
                available=True,
                model_available=False,
                detail="configured model is not available",
            ),
            "model is not available",
        ),
        (
            ProbeResult(
                provider="ollama",
                available=False,
                model_available=True,
                schema_available=False,
                detail="strict JSON schema capability is unavailable",
            ),
            "schema capability is unavailable",
        ),
    ],
)
def test_llm_doctor_distinguishes_unverifiable_causes(
    monkeypatch: pytest.MonkeyPatch,
    probe: ProbeResult,
    expected_detail: str,
) -> None:
    class FakeOllamaProvider:
        def __init__(self, config: object) -> None:
            del config

        def health_check(self) -> ProbeResult:
            return probe

    monkeypatch.setattr(cli_module, "OllamaProvider", FakeOllamaProvider)

    result = runner.invoke(app, ["llm", "doctor", "--provider", "ollama"])

    assert result.exit_code == 0
    assert "status=UNVERIFIABLE" in result.stdout
    assert expected_detail in result.stdout
