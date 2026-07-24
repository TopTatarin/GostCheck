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
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.table import Table

from normocontrol.cache import LockError
from normocontrol.domain import ExitCode, RunReport, StageResult
from normocontrol.errors import ConfigurationError, LocatedValidationError
from normocontrol.extract.base import DocumentBundle, ExtractionError
from normocontrol.extract.latex import LatexExtractor
from normocontrol.extract.pdf import PdfExtractor
from normocontrol.llm.base import LlmProvider
from normocontrol.llm.config import ProviderName, load_llm_config
from normocontrol.llm.disabled import DisabledProvider
from normocontrol.llm.ollama import OllamaProvider
from normocontrol.llm.yandex import YandexProvider
from normocontrol.orchestrator import run_pipeline
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_effective_rubric, load_rubric
from normocontrol.rubric.models import EffectiveRubric, NormocontrolConfig, WorkProfile
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry
from normocontrol.run_context import RunRequest, parse_only
from normocontrol.semantic.engine import SemanticEngine

app = typer.Typer(no_args_is_help=True, help="Автоматизированный нормоконтроль ВКР.")
rubric_app = typer.Typer(no_args_is_help=True, help="Проверка и просмотр рубрики.")
llm_app = typer.Typer(no_args_is_help=True, help="Диагностика LLM-провайдеров.")
app.add_typer(rubric_app, name="rubric")
app.add_typer(llm_app, name="llm")


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


@dataclass(frozen=True, slots=True)
class CliState:
    """Global command-line switches shared by subcommands."""

    no_llm: bool = False


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


def load_effective_rubric_for_check(
    rubric_path: Path,
    config_path: Path,
    profile: str | None = None,
) -> tuple[EffectiveRubric, NormocontrolConfig]:
    """Load rubric/config and optionally override the work profile."""
    config = load_config(config_path)
    if profile is not None:
        try:
            chosen = WorkProfile(profile)
        except ValueError as error:
            msg = f"unknown profile: {profile}"
            raise typer.BadParameter(msg) from error
        config = config.model_copy(update={"work_profile": chosen})
    return expand_rubric(load_rubric(rubric_path), config), config


def run_formal_check(
    source: Path,
    *,
    rubric_path: Path,
    config_path: Path,
    profile: str | None = None,
    project_root: Path | None = None,
) -> RunReport:
    """Extract inputs and run deterministic formal rules."""
    rubric, config = load_effective_rubric_for_check(rubric_path, config_path, profile)
    root = project_root or source.parent
    suffix = source.suffix.casefold()
    latex: LatexProject | None = None
    pdf_path: Path | None = None
    if suffix == ".tex":
        resolved = source.resolve()
        latex = LatexProject(root=root.resolve(), main_tex=resolved)
        bundle = LatexExtractor(root).extract(resolved)
    elif suffix == ".pdf":
        pdf_path = source.resolve()
        bundle = PdfExtractor(root).extract(pdf_path)
    else:
        raise ExtractionError("supported source extensions are .tex and .pdf")

    context = ExecutionContext(
        rubric=rubric,
        config=config,
        bundle=bundle,
        latex=latex,
        pdf_path=pdf_path,
        bib_paths=(),
    )
    result = FormalEngine(default_formal_registry()).run(context)
    return RunReport(
        tool_version=package_version(),
        exit_code=ExitCode(result.exit_code),
        stages=(StageResult(name="formal", findings=result.findings),),
    )


@app.callback()
def main(
    ctx: typer.Context,
    version_requested: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Показать версию и выйти.",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Отключить все LLM-вызовы независимо от переменных окружения.",
    ),
) -> None:
    """Run the GostCheck command-line interface."""
    del version_requested
    ctx.obj = CliState(no_llm=no_llm)


@app.command()
def doctor() -> None:
    """Check local prerequisites; missing optional tools do not change exit code 0."""
    render_doctor(collect_doctor_checks())


@llm_app.command("doctor")
def llm_doctor(
    ctx: typer.Context,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="disabled, ollama или yandex; CLI имеет приоритет."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="OpenAI-совместимый базовый URL."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Локальная модель Ollama; Yandex URI задаётся через env."),
    ] = None,
) -> None:
    """Probe ``/models``; provider failures remain advisory and exit successfully."""
    state = ctx.find_root().obj
    no_llm = isinstance(state, CliState) and state.no_llm
    try:
        config = load_llm_config(
            provider_override=provider,
            base_url_override=base_url,
            model_override=model,
            no_llm=no_llm,
        )
    except ConfigurationError as error:
        typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1) from error

    selected: LlmProvider
    if config.provider is ProviderName.DISABLED:
        selected = DisabledProvider()
    elif config.provider is ProviderName.OLLAMA:
        selected = OllamaProvider(config)
    else:
        selected = YandexProvider(config)
    probe = selected.health_check()
    status = "OK" if probe.available and probe.model_available else "UNVERIFIABLE"
    if config.provider is ProviderName.DISABLED:
        status = "SKIPPED"
    typer.echo(f"provider={probe.provider} status={status} detail={probe.detail}")


def emit_bundle(bundle: DocumentBundle, output_path: Path) -> None:
    """Write a bundle as deterministic UTF-8 JSON, creating only its parent directory."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        f"{bundle.model_dump_json(indent=2)}\n",
        encoding="utf-8",
        newline="\n",
    )


@app.command("semantic")
def semantic_command(
    ctx: typer.Context,
    bundle_path: Annotated[Path, typer.Argument(help="DocumentBundle JSON из команды extract.")],
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="disabled, ollama или yandex; CLI имеет приоритет."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Модель для локального провайдера."),
    ] = None,
) -> None:
    """Run merge-safe semantic checks and emit a deterministic JSON report."""
    state = ctx.find_root().obj
    no_llm = isinstance(state, CliState) and state.no_llm
    try:
        config = load_llm_config(
            provider_override=provider,
            model_override=model,
            no_llm=no_llm,
        )
        bundle = DocumentBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    except (ConfigurationError, OSError, ValidationError) as error:
        typer.echo(f"ERROR cannot load semantic input: {type(error).__name__}", err=True)
        raise typer.Exit(code=1) from error

    selected: LlmProvider
    if config.provider is ProviderName.DISABLED:
        selected = DisabledProvider()
    elif config.provider is ProviderName.OLLAMA:
        selected = OllamaProvider(config)
    else:
        selected = YandexProvider(config)
    model_id = config.model or selected.name
    report = SemanticEngine(selected, model_id=model_id).run(bundle)
    sys.stdout.write(f"{report.model_dump_json(indent=2)}\n")


@app.command("run")
def run_command(
    ctx: typer.Context,
    source: Annotated[
        Path,
        typer.Argument(help="Каталог с main.tex/main.pdf либо путь к .tex/.pdf."),
    ],
    config: Annotated[Path, typer.Option("--config", help="Путь к конфигурации.")] = Path(
        "normocontrol.yaml.example"
    ),
    rubric: Annotated[Path, typer.Option("--rubric", help="Путь к rubric.yaml.")] = Path(
        "rubric.yaml"
    ),
    out: Annotated[Path, typer.Option("--out", help="Каталог артефактов прогона.")] = Path(
        "build/normocontrol"
    ),
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="software, research или organizational."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="disabled, ollama или yandex; CLI имеет приоритет."),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            help="Стадия (build/formal/semantic/aggregate) или префикс правила.",
        ),
    ] = None,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Отключить semantic LLM для этого прогона."),
    ] = False,
    final: Annotated[
        bool,
        typer.Option("--final", help="Применить severity_final (например ANN-03/REV-01)."),
    ] = False,
    fail_closed: Annotated[
        bool,
        typer.Option("--fail-closed", help="Инструментальные сбои formal/build дают exit 4."),
    ] = False,
) -> None:
    """Run build -> formal -> semantic -> aggregate with documented exit codes."""
    state = ctx.find_root().obj
    global_no_llm = isinstance(state, CliState) and state.no_llm
    try:
        only_filter = parse_only(tuple(only) if only else None)
        request = RunRequest(
            source=source,
            out_dir=out,
            config_path=config,
            rubric_path=rubric,
            profile=profile,
            no_llm=global_no_llm or no_llm,
            provider=provider,
            only=only_filter,
            apply_final_severity=final,
            fail_closed=fail_closed,
            tool_version=package_version(),
        )
        report = run_pipeline(request)
    except ConfigurationError as error:
        typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=int(ExitCode.CONFIG_ERROR)) from error
    except LocatedValidationError as error:
        typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=int(ExitCode.CONFIG_ERROR)) from error
    except LockError as error:
        typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=int(ExitCode.CONFIG_ERROR)) from error
    except Exception as error:
        typer.echo(f"ERROR internal failure: {type(error).__name__}", err=True)
        raise typer.Exit(code=int(ExitCode.INTERNAL_ERROR)) from error

    # Published artifacts are written by the orchestrator aggregate stage.
    raise typer.Exit(code=int(report.exit_code))


@app.command("check")
def check_command(
    source: Annotated[Path, typer.Argument(help="Главный .tex или PDF-файл.")],
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="software, research или organizational."),
    ] = None,
    rubric: Annotated[Path, typer.Option("--rubric", help="Путь к rubric.yaml.")] = Path(
        "rubric.yaml"
    ),
    config: Annotated[Path, typer.Option("--config", help="Путь к конфигурации.")] = Path(
        "normocontrol.yaml.example"
    ),
    output: Annotated[Path | None, typer.Option("--out", help="JSON-отчёт RunReport.")] = None,
    project_root: Annotated[
        Path | None,
        typer.Option("--project-root", help="Корень LaTeX-проекта для include."),
    ] = None,
) -> None:
    """Run deterministic formal checks and emit a RunReport JSON."""
    try:
        report = run_formal_check(
            source,
            rubric_path=rubric,
            config_path=config,
            profile=profile,
            project_root=project_root,
        )
    except (ExtractionError, LocatedValidationError) as error:
        typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1) from error

    emit_report(report, output)
    raise typer.Exit(code=int(report.exit_code))


@app.command("extract")
def extract_command(
    source: Annotated[Path, typer.Argument(help="Главный .tex или PDF-файл.")],
    output: Annotated[Path, typer.Option("--out", help="Выходной DocumentBundle JSON.")],
    project_root: Annotated[
        Path | None,
        typer.Option("--project-root", help="Корень для безопасного раскрытия LaTeX include."),
    ] = None,
    token_budget: Annotated[
        int,
        typer.Option("--token-budget", min=1, help="Максимальный бюджет одного chunk."),
    ] = 800,
) -> None:
    """Safely extract LaTeX/PDF into a local, addressable DocumentBundle."""
    root = project_root or source.parent
    suffix = source.suffix.casefold()
    try:
        if suffix == ".tex":
            bundle = LatexExtractor(root, token_budget=token_budget).extract(source)
        elif suffix == ".pdf":
            bundle = PdfExtractor(root, token_budget=token_budget).extract(source)
        else:
            raise ExtractionError("supported source extensions are .tex and .pdf")
        emit_bundle(bundle, output)
    except ExtractionError as error:
        typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1) from error


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
