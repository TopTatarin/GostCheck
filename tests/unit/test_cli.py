import io
from pathlib import Path

import pytest
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.cli import app
from normocontrol.domain import (
    ExitCode,
    Finding,
    FindingStatus,
    RuleLayer,
    RunReport,
    Severity,
    StageResult,
)

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


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [
        (ExitCode.SUCCESS, 0),
        (ExitCode.FORMAL_FAILURE, 2),
    ],
)
def test_run_preserves_computed_exit_with_strict_cp1251_redirected_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exit_code: ExitCode,
    expected: int,
) -> None:
    stages = (
        (
            StageResult(
                name="formal",
                findings=(
                    Finding(
                        rule_id="FMT-01",
                        layer=RuleLayer.SCRIPT,
                        severity=Severity.ERROR,
                        status=FindingStatus.FAIL,
                        message="synthetic formal failure",
                    ),
                ),
            ),
        )
        if exit_code is ExitCode.FORMAL_FAILURE
        else ()
    )
    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda request: RunReport(
            tool_version=request.tool_version,
            exit_code=exit_code,
            stages=stages,
        ),
    )
    stdout_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1251", errors="strict")
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    context = cli.typer.Context(cli.typer.main.get_command(cli.app))

    with pytest.raises(cli.typer.Exit) as raised:
        cli.run_command(
            ctx=context,
            source=tmp_path / "ВКР_а\u0301_📄_╨╨.pdf",
            config=Path("normocontrol.yaml.example"),
            rubric=Path("rubric.yaml"),
            out=tmp_path / "отчёт",
            profile=None,
            provider="disabled",
            model=None,
            base_url=None,
            only=None,
            no_llm=True,
            final=False,
            fail_closed=False,
        )

    stdout.flush()
    output = stdout_bytes.getvalue().decode("cp1251")
    assert raised.value.exit_code == expected
    assert "\\u0301" in output
    assert "\\U0001f4c4" in output
    assert "\\u2568\\u2568" in output
