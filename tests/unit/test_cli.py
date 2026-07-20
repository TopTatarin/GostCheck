from typer.testing import CliRunner

from normocontrol.cli import app

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

