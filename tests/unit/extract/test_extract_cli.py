from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from normocontrol.cli import app
from normocontrol.extract.base import DocumentBundle

ROOT = Path(__file__).parents[3]
MINIMAL = ROOT / "tests" / "fixtures" / "extract" / "minimal"


def test_extract_cli_writes_utf8_bundle(tmp_path: Path) -> None:
    output = tmp_path / "каталог с пробелом" / "bundle.json"
    result = CliRunner().invoke(
        app,
        ["extract", str(MINIMAL / "main.tex"), "--out", str(output)],
    )

    assert result.exit_code == 0, result.output
    bundle = DocumentBundle.model_validate_json(output.read_text(encoding="utf-8"))
    assert bundle.source_files[0].path == "main.tex"
    assert "введение" in bundle.text.casefold()


def test_extract_cli_rejects_unknown_format_without_traceback(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("synthetic", encoding="utf-8")

    result = CliRunner().invoke(app, ["extract", str(source), "--out", str(tmp_path / "out.json")])

    assert result.exit_code == 1
    assert "supported source extensions" in result.stderr
    assert "synthetic" not in result.stderr
