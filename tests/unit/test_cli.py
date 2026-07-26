from pathlib import Path

import pytest
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.cli import app
from normocontrol.domain import ExitCode, RunReport

runner = CliRunner()


def test_version_is_available() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_doctor_does_not_fail_when_optional_tools_are_missing() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Python 3.12" in result.stdout
    assert "Ollama (optional)" in result.stdout


def test_run_prints_summary_for_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda request: RunReport(tool_version=request.tool_version),
    )

    result = runner.invoke(
        app,
        [
            "--no-llm",
            "run",
            str(tmp_path / "Синтетическая ВКР"),
            "--out",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == int(ExitCode.SUCCESS)
    assert "GostCheck run summary" in result.stdout
    assert "gate: PASS" in result.stdout
    assert "provider: disabled" in result.stdout
    assert "report.md:" in result.stdout
    assert "report.json:" in result.stdout
    assert "exit_code: 0 (success; advisory findings do not block)" in result.stdout


def test_run_prints_exit_four_summary_without_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_pipeline(request: object) -> RunReport:
        del request
        raise RuntimeError("raw_prompt='THESIS TEXT' api_key=sk-secret-value")

    monkeypatch.setattr(cli, "run_pipeline", fail_pipeline)

    result = runner.invoke(
        app,
        [
            "--no-llm",
            "run",
            str(tmp_path / "input.pdf"),
            "--out",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == int(ExitCode.INTERNAL_ERROR)
    assert "gate: FAIL" in result.stdout
    assert "exit_code: 4 (internal or tool error)" in result.stdout
    assert "RuntimeError" in result.stdout
    assert "THESIS TEXT" not in result.stdout + result.stderr
    assert "sk-secret-value" not in result.stdout + result.stderr
