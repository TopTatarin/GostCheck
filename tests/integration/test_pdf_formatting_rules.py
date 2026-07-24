"""Integration tests for D-03 PDF formatting rules."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from normocontrol.domain import ExitCode, FindingStatus
from normocontrol.extract.pdf import PdfExtractor
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "latex"
RUBRIC_PATH = ROOT / "rubric.yaml"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"

FMT_RULES = frozenset({"FMT-01", "FMT-02", "FMT-03", "FMT-04", "FMT-05"})


def _save_pdf(document: fitz.Document, path: Path) -> Path:
    document.save(path)
    document.close()
    return path


def _pass_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((100, 80), "Heading", fontsize=14, fontname="tibo")
    for index in range(8):
        page.insert_text(
            (100, 120 + index * 21),
            f"Body line {index} with enough text for spacing checks.",
            fontsize=14,
            fontname="tiro",
        )
    return _save_pdf(document, path)


def _wrong_font_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((100, 120), "Body only", fontsize=14, fontname="helv")
    return _save_pdf(document, path)


def _non_bold_heading_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((100, 80), "Heading", fontsize=16, fontname="tiro")
    page.insert_text((100, 120), "Body text", fontsize=14, fontname="tiro")
    return _save_pdf(document, path)


def _margin_overflow_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((10, 40), "Too close to the edge", fontsize=14, fontname="tiro")
    return _save_pdf(document, path)


def _effective_rubric():
    config = load_config(CONFIG_PATH)
    return expand_rubric(load_rubric(RUBRIC_PATH), config)


def _run_with_pdf(pdf_path: Path, *, latex_fixture: str = "pass"):
    project_root = FIXTURES / latex_fixture
    bundle = PdfExtractor(pdf_path.parent).extract(pdf_path)
    context = ExecutionContext(
        rubric=_effective_rubric(),
        config=load_config(CONFIG_PATH),
        bundle=bundle,
        latex=LatexProject(root=project_root, main_tex=project_root / "main.tex"),
        pdf_path=pdf_path.resolve(),
        bib_paths=(),
    )
    result = FormalEngine(default_formal_registry()).run(context)
    fmt_findings = tuple(finding for finding in result.findings if finding.rule_id in FMT_RULES)
    return result, fmt_findings


def _statuses(findings, rule_id: str) -> tuple[FindingStatus, ...]:
    return tuple(finding.status for finding in findings if finding.rule_id == rule_id)


def test_pass_pdf_and_class_passes_fmt_rules(tmp_path: Path) -> None:
    pdf_path = _pass_pdf(tmp_path / "pass.pdf")
    result, findings = _run_with_pdf(pdf_path)
    blocking = tuple(
        finding
        for finding in findings
        if finding.status is FindingStatus.FAIL and finding.severity.value == "error"
    )
    assert not blocking, [(item.rule_id, item.message) for item in blocking]
    assert result.exit_code == int(ExitCode.SUCCESS)


@pytest.mark.parametrize(
    ("builder", "rule_id"),
    [
        (_wrong_font_pdf, "FMT-01"),
        (_non_bold_heading_pdf, "FMT-02"),
        (_margin_overflow_pdf, "FMT-05"),
    ],
)
def test_pdf_failures_trigger_expected_fmt_rule(
    tmp_path: Path,
    builder,
    rule_id: str,
) -> None:
    pdf_path = builder(tmp_path / f"{rule_id}.pdf")
    _, findings = _run_with_pdf(pdf_path)
    assert FindingStatus.FAIL in _statuses(findings, rule_id)
