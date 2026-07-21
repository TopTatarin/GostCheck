from __future__ import annotations

from typer.testing import CliRunner

from normocontrol.cli import app

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
