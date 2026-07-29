from __future__ import annotations

import io
import logging
import unicodedata
from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.domain import ExitCode, RunReport
from normocontrol.errors import ConfigurationError
from normocontrol.logging import RedactingFormatter, SecretRedactionFilter, redact_text
from normocontrol.reporting.console import console_safe_text

runner = CliRunner()


def test_help_and_version_return_success() -> None:
    help_result = runner.invoke(cli.app, ["--help"])
    version_result = runner.invoke(cli.app, ["--version"])

    assert help_result.exit_code == ExitCode.SUCCESS
    assert "doctor" in help_result.stdout
    assert version_result.exit_code == ExitCode.SUCCESS
    assert version_result.stdout.strip() == "0.1.0"


def test_package_version_has_source_tree_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_distribution(_: str) -> str:
        raise cli.PackageNotFoundError

    monkeypatch.setattr(cli, "version", missing_distribution)

    assert cli.package_version() == "0.1.0"


def test_doctor_is_offline_and_non_blocking_when_binaries_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "Python 3.12" in result.stdout
    assert "Git" in result.stdout
    assert "latexmk" in result.stdout
    assert "chktex" in result.stdout
    assert "LLM provider" in result.stdout
    assert "not found" in result.stdout


@pytest.mark.parametrize(
    ("settings", "expected_available", "expected_detail"),
    [
        (cli.DoctorSettings(llm_provider="disabled"), True, "disabled by configuration"),
        (cli.DoctorSettings(llm_provider="openai"), False, "credentials not configured"),
        (
            cli.DoctorSettings(
                llm_provider="openai",
                openai_api_key=SecretStr("sk-unit-test-secret"),
            ),
            True,
            "credentials configured",
        ),
    ],
)
def test_doctor_reports_llm_configuration_without_exposing_secrets(
    monkeypatch: pytest.MonkeyPatch,
    settings: cli.DoctorSettings,
    expected_available: bool,
    expected_detail: str,
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)

    checks = cli.collect_doctor_checks(settings)
    llm_check = next(check for check in checks if check.component == "LLM provider")

    assert llm_check.available is expected_available
    assert llm_check.detail == expected_detail
    assert "sk-unit-test-secret" not in repr(settings)


def test_doctor_detects_local_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/tools/{name}")

    checks = cli.collect_doctor_checks(cli.DoctorSettings(llm_provider="ollama"))

    assert checks[-1].available is True
    assert checks[-1].detail == "local executable"


def test_doctor_renders_on_cp1251_terminal() -> None:
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1251", errors="strict")

    cli.render_doctor((cli.DoctorCheck("Python 3.12", True, "готов 📄 ╨╨"),), stream)
    stream.flush()

    output = buffer.getvalue().decode("cp1251")
    assert "готов" in output
    assert "\\U0001f4c4" in output
    assert "\\u2568\\u2568" in output


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ВКР_Золоева.pdf", "ВКР_Золоева.pdf"),
        ("ВКР_Золое\u0308ва.pdf", "ВКР_Золоёва.pdf"),
        ("ВКР_а\u0301.pdf", "ВКР_а\\u0301.pdf"),
        ("ВКР_📄.pdf", "ВКР_\\U0001f4c4.pdf"),
        ("ВКР_╨.pdf", "ВКР_\\u2568.pdf"),
        ("ВКР_╨╨╨.pdf", "ВКР_\\u2568\\u2568\\u2568.pdf"),
    ],
)
def test_console_safe_text_normalizes_nfc_and_escapes_for_cp1251(
    value: str,
    expected: str,
) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1251", errors="strict")

    result = console_safe_text(value, stream)

    assert result == expected
    assert unicodedata.is_normalized("NFC", result)


def test_emit_report_uses_stdout_or_utf8_path_with_spaces_and_nfd(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = RunReport(tool_version="0.1.0")
    nfd_name = "re\u0301port.json"
    report_path = tmp_path / "каталог с пробелом" / nfd_name
    report_path.parent.mkdir()

    cli.emit_report(report)
    stdout = capsys.readouterr().out
    cli.emit_report(report, report_path)

    assert RunReport.model_validate_json(stdout) == report
    assert RunReport.model_validate_json(report_path.read_text(encoding="utf-8")) == report


def test_exception_logs_redact_api_keys_and_document_payloads() -> None:
    secret = "sk-super-secret-value"
    error = ConfigurationError(f"api_key={secret}")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("normocontrol.test.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    try:
        raise error
    except ConfigurationError:
        logger.exception("settings=%r thesis_text='секретный фрагмент'", error)

    output = stream.getvalue()
    assert secret not in output
    assert "секретный фрагмент" not in output
    assert "[REDACTED]" in output


def test_redaction_bounds_untrusted_log_messages() -> None:
    result = redact_text("x" * 600)

    assert len(result) < 600
    assert result.endswith("...[TRUNCATED]")
