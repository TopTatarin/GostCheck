"""Command-line interface for GostCheck."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, TextIO

import typer
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.table import Table

from normocontrol.domain import RunReport
from normocontrol.errors import LocatedValidationError
from normocontrol.rubric.loader import load_effective_rubric

app = typer.Typer(no_args_is_help=True, help="Автоматизированный нормоконтроль ВКР.")
rubric_app = typer.Typer(no_args_is_help=True, help="Проверка и просмотр рубрики.")
app.add_typer(rubric_app, name="rubric")


class DoctorSettings(BaseSettings):
    """Environment-only settings needed for offline diagnostics."""

    model_config = SettingsConfigDict(extra="ignore", env_file=None)

    llm_provider: str = "disabled"
    openai_api_key: SecretStr | None = None


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One side-effect-free doctor check result."""

    component: str
    available: bool
    detail: str = ""


def package_version() -> str:
    """Return installed package version, including editable installs."""
    try:
        return version("gostcheck")
    except PackageNotFoundError:
        return "0.1.0"


def version_callback(value: bool) -> None:
    """Print the version requested by Typer's eager option."""
    if value:
        typer.echo(package_version())
        raise typer.Exit


def collect_doctor_checks(settings: DoctorSettings | None = None) -> tuple[DoctorCheck, ...]:
    """Inspect local executables and configuration without network access."""
    current_settings = settings or DoctorSettings()
    provider = current_settings.llm_provider.strip().lower()
    ollama_available = shutil.which("ollama") is not None

    if provider == "disabled":
        llm_available = True
        llm_detail = "disabled by configuration"
    elif provider == "ollama":
        llm_available = ollama_available
        llm_detail = "local executable" if llm_available else "ollama executable not found"
    else:
        llm_available = current_settings.openai_api_key is not None
        llm_detail = "credentials configured" if llm_available else "credentials not configured"

    return (
        DoctorCheck("Python 3.12", sys.version_info[:2] == (3, 12), sys.version.split()[0]),
        DoctorCheck("Git", shutil.which("git") is not None),
        DoctorCheck("latexmk", shutil.which("latexmk") is not None),
        DoctorCheck("chktex", shutil.which("chktex") is not None),
        DoctorCheck("Ollama (optional)", ollama_available),
        DoctorCheck("LLM provider", llm_available, llm_detail),
    )


def render_doctor(checks: Sequence[DoctorCheck], output: TextIO | None = None) -> None:
    """Render doctor diagnostics to a terminal-safe plain table."""
    console = Console(
        file=output or sys.stdout,
        force_terminal=False,
        color_system=None,
        soft_wrap=True,
    )
    table = Table(title="GostCheck doctor", box=None, show_header=True)
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Details")
    for check in checks:
        table.add_row(check.component, "OK" if check.available else "not found", check.detail)
    console.print(table)


def emit_report(report: RunReport, output_path: Path | None = None) -> None:
    """Write only report JSON to stdout or to a UTF-8 file."""
    payload = f"{report.model_dump_json(indent=2)}\n"
    if output_path is None:
        sys.stdout.write(payload)
        return
    output_path.write_text(payload, encoding="utf-8", newline="\n")


@app.callback()
def main(
    version_requested: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Показать версию и выйти.",
    ),
) -> None:
    """Run the GostCheck command-line interface."""


@app.command()
def doctor() -> None:
    """Check local prerequisites; missing optional tools do not change exit code 0."""
    render_doctor(collect_doctor_checks())


@rubric_app.command("validate")
def rubric_validate(
    rubric: Annotated[Path, typer.Option("--rubric", help="Путь к rubric.yaml.")] = Path(
        "rubric.yaml"
    ),
    config: Annotated[Path, typer.Option("--config", help="Путь к конфигурации.")] = Path(
        "normocontrol.yaml"
    ),
) -> None:
    """Validate rubric and explicit profile; invalid input exits with code 3."""
    try:
        effective = load_effective_rubric(rubric, config)
    except LocatedValidationError as error:
        typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=3) from error

    counts = {severity: 0 for severity in ("error", "warn", "info")}
    for rule in effective.rules:
        counts[rule.severity.value] += 1
    typer.echo(
        f"OK: 64 rules; severity error={counts['error']}, "
        f"warn={counts['warn']}, info={counts['info']}; "
        f"profile={effective.work_profile.value}"
    )
    for warning in effective.warnings:
        typer.echo(f"WARNING {warning.code} {warning.yaml_path}: {warning.message}")


if __name__ == "__main__":
    app()
