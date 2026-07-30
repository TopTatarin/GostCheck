"""Unit tests for the ``--gate-mode`` CLI option and its configuration key."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.cli import app, parse_gate_mode
from normocontrol.domain import ExitCode, GateMode, RunReport
from normocontrol.errors import ConfigurationError, LocatedValidationError
from normocontrol.rubric.loader import load_config
from normocontrol.run_context import RunRequest

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[2]
CONFIG_EXAMPLE = ROOT / "normocontrol.yaml.example"


def _write_config(path: Path, *, gate_mode: str | None) -> Path:
    lines = ["version: 1", "work_profile: software"]
    if gate_mode is not None:
        lines.append(f"gate_mode: {gate_mode}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("strict", GateMode.STRICT),
        ("advisory", GateMode.ADVISORY),
        ("  ADVISORY  ", GateMode.ADVISORY),
    ],
)
def test_parse_gate_mode_accepts_documented_values(
    value: str | None,
    expected: GateMode | None,
) -> None:
    assert parse_gate_mode(value) is expected


@pytest.mark.parametrize("value", ["", "lenient", "Strict!", "0"])
def test_parse_gate_mode_rejects_unknown_values(value: str) -> None:
    with pytest.raises(ConfigurationError, match="unknown gate mode"):
        parse_gate_mode(value)


def test_run_forwards_gate_mode_to_the_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[RunRequest] = []

    def capture(request: RunRequest) -> RunReport:
        seen.append(request)
        return RunReport(tool_version=request.tool_version)

    monkeypatch.setattr(cli, "run_pipeline", capture)

    result = runner.invoke(
        app,
        [
            "--no-llm",
            "run",
            str(tmp_path / "src"),
            "--out",
            str(tmp_path / "out"),
            "--gate-mode",
            "advisory",
        ],
    )

    assert result.exit_code == int(ExitCode.SUCCESS)
    assert seen[0].gate_mode is GateMode.ADVISORY


def test_run_without_flag_leaves_gate_mode_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unset request mode lets the configuration decide; the default stays strict."""
    seen: list[RunRequest] = []

    def capture(request: RunRequest) -> RunReport:
        seen.append(request)
        return RunReport(tool_version=request.tool_version)

    monkeypatch.setattr(cli, "run_pipeline", capture)

    result = runner.invoke(
        app,
        ["--no-llm", "run", str(tmp_path / "src"), "--out", str(tmp_path / "out")],
    )

    assert result.exit_code == int(ExitCode.SUCCESS)
    assert seen[0].gate_mode is None


def test_run_rejects_unknown_gate_mode_with_config_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--no-llm",
            "run",
            str(tmp_path / "src"),
            "--out",
            str(tmp_path / "out"),
            "--gate-mode",
            "lenient",
        ],
    )

    assert result.exit_code == int(ExitCode.CONFIG_ERROR)
    assert "unknown gate mode: lenient" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_check_rejects_unknown_gate_mode_with_config_error(tmp_path: Path) -> None:
    source = tmp_path / "main.tex"
    source.write_text("\\documentclass{article}\n", encoding="utf-8")

    result = runner.invoke(app, ["check", str(source), "--gate-mode", "lenient"])

    assert result.exit_code == int(ExitCode.CONFIG_ERROR)
    assert "unknown gate mode: lenient" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_run_help_documents_gate_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import typer.rich_utils as rich_utils

    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", False)
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--gate-mode" in result.stdout


def test_check_help_documents_gate_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import typer.rich_utils as rich_utils

    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", False)
    result = runner.invoke(app, ["check", "--help"])

    assert result.exit_code == 0
    assert "--gate-mode" in result.stdout


def test_config_default_gate_mode_is_strict(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path / "normocontrol.yaml", gate_mode=None))

    assert config.gate_mode is GateMode.STRICT


def test_config_accepts_advisory_gate_mode(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path / "normocontrol.yaml", gate_mode="advisory"))

    assert config.gate_mode is GateMode.ADVISORY


def test_shipped_example_config_is_strict() -> None:
    assert load_config(CONFIG_EXAMPLE).gate_mode is GateMode.STRICT


def test_config_rejects_unknown_gate_mode(tmp_path: Path) -> None:
    path = _write_config(tmp_path / "normocontrol.yaml", gate_mode="lenient")

    with pytest.raises(LocatedValidationError) as error:
        load_config(path)

    assert "gate_mode" in str(error.value)


def test_run_reports_config_error_for_unknown_gate_mode_in_config(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "normocontrol.yaml", gate_mode="lenient")
    source = tmp_path / "main.tex"
    source.write_text("\\documentclass{article}\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--no-llm",
            "run",
            str(source),
            "--config",
            str(config),
            "--rubric",
            str(ROOT / "rubric.yaml"),
            "--out",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == int(ExitCode.CONFIG_ERROR)
    assert "Traceback" not in result.stdout + result.stderr
    assert "gate_mode" in result.stdout
