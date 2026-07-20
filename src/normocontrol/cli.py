"""Command-line interface for GostCheck."""

from __future__ import annotations

import shutil
import sys
from importlib.metadata import PackageNotFoundError, version

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, help="Автоматизированный нормоконтроль ВКР.")
console = Console()


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
    """Show whether required and optional local tools are available."""
    checks = {
        "Python 3.12": sys.version_info[:2] == (3, 12),
        "Git": shutil.which("git") is not None,
        "latexmk": shutil.which("latexmk") is not None,
        "chktex": shutil.which("chktex") is not None,
        "Ollama (optional)": shutil.which("ollama") is not None,
    }
    table = Table(title="GostCheck doctor")
    table.add_column("Component")
    table.add_column("Status")
    for name, available in checks.items():
        table.add_row(name, "OK" if available else "not found")
    console.print(table)


if __name__ == "__main__":
    app()

