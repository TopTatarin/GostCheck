"""Integration tests for D-03 PDF formatting rules."""

from __future__ import annotations

import re
from pathlib import Path

import fitz
import pytest

from normocontrol.domain import ExitCode, FindingStatus
from normocontrol.extract.pdf import PdfExtractor
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.gate import formal_exit_code
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


def _rename_embedded_font(
    document: fitz.Document,
    font_xrefs: set[int],
    alias: str,
) -> None:
    """Give a synthetic embedded font a deterministic PDF BaseFont alias."""
    for font_xref in font_xrefs:
        document.xref_set_key(font_xref, "BaseFont", f"/{alias}")
        _, descendants = document.xref_get_key(font_xref, "DescendantFonts")
        descendant_values = re.findall(r"\d+(?=\s+0\s+R)", descendants)
        for descendant_xref in (int(value) for value in descendant_values):
            document.xref_set_key(descendant_xref, "BaseFont", f"/{alias}")
            _, descriptor = document.xref_get_key(descendant_xref, "FontDescriptor")
            descriptor_match = re.search(r"(\d+)\s+0\s+R", descriptor)
            if descriptor_match is not None:
                document.xref_set_key(
                    int(descriptor_match.group(1)),
                    "FontName",
                    f"/{alias}",
                )


def _tempora_multipage_pdf(path: Path) -> Path:
    document = fitz.open()
    font_buffer = fitz.Font(fontname="tiro").buffer
    font_xrefs: set[int] = set()
    for page_number in range(1, 4):
        page = document.new_page(width=595, height=842)
        font_xrefs.add(page.insert_font(fontname="SyntheticBody", fontbuffer=font_buffer))
        page.insert_text(
            (100, 80),
            f"Synthetic heading {page_number}",
            fontsize=16,
            fontname="hebo",
        )
        for line_number in range(8):
            page.insert_text(
                (100, 120 + line_number * 21),
                f"Body page {page_number} line {line_number} with synthetic content.",
                fontsize=14,
                fontname="SyntheticBody",
            )
        page.insert_text(
            (30, 820),
            f"Synthetic department footer {page_number}",
            fontsize=10,
            fontname="SyntheticBody",
        )
    _rename_embedded_font(document, font_xrefs, "Tempora-Regular")
    return _save_pdf(document, path)


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


def _fmt01_mixed_context_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((100, 80), "Synthetic heading", fontsize=18, fontname="hebo")
    for index in range(8):
        page.insert_text(
            (100, 120 + index * 21),
            f"Ordinary Times body line {index} with sufficient synthetic content.",
            fontsize=14,
            fontname="tiro",
        )
    page.insert_text((100, 300), "Use ", fontsize=14, fontname="tiro")
    page.insert_text((126, 300), "token", fontsize=14, fontname="cour")
    page.insert_text(
        (168, 300),
        " in an ordinary inline-code sentence.",
        fontsize=14,
        fontname="tiro",
    )
    page.insert_text((100, 340), "Table 1 - Synthetic metrics", fontsize=10, fontname="tiro")
    for row, (label, value) in enumerate(
        (("Metric", "Value"), ("Alpha", "10"), ("Beta", "20")),
    ):
        y = 365 + row * 15
        page.insert_text((100, y), label, fontsize=10, fontname="tiro")
        page.insert_text((300, y), value, fontsize=10, fontname="tiro")
    for index, text in enumerate(
        ("for item in values:", "    print(item)", "    return item"),
    ):
        page.insert_text((110, 430 + index * 15), text, fontsize=10, fontname="cour")
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


def _graphic_overflow_pdf(path: Path, kind: str) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text(
        (100, 120),
        "Synthetic body remains within margins.",
        fontsize=14,
        fontname="tiro",
    )
    overflow_rect = fitz.Rect(10, 180, 180, 260)
    if kind == "image":
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
        pixmap.clear_with(220)
        page.insert_image(overflow_rect, pixmap=pixmap)
    else:
        page.draw_rect(overflow_rect, width=1)
        page.draw_line((10, 220), (180, 220), width=1)
    return _save_pdf(document, path)


def _bounded_vector_pdf(path: Path, *, page_number: int, overflow_pt: float) -> Path:
    document = fitz.open()
    for index in range(page_number):
        page = document.new_page(width=595, height=842)
        page.insert_text(
            (100, 120),
            f"Synthetic body remains within margins on page {index + 1}.",
            fontsize=14,
            fontname="tiro",
        )
    left_bound = 30.0 * 72.0 / 25.4 - 2.0 * 72.0 / 25.4
    document[page_number - 1].draw_rect(
        fitz.Rect(left_bound - overflow_pt, 180, left_bound + 100, 260),
        width=1,
    )
    return _save_pdf(document, path)


def _long_table_footer_overflow_pdf(path: Path, *, overflow_pt: float) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text(
        (100, 120),
        "Synthetic body remains within margins.",
        fontsize=14,
        fontname="tiro",
    )
    bottom_bound = 842 - 20.0 * 72.0 / 25.4 + 2.0 * 72.0 / 25.4
    page.draw_rect(
        fitz.Rect(100, 650, 500, bottom_bound + overflow_pt),
        width=1,
    )
    for y in (700, 750, bottom_bound + overflow_pt - 12):
        page.draw_line((100, y), (500, y), width=1)
    page.insert_text(
        (110, bottom_bound - 4),
        "Long table final row",
        fontsize=10,
        fontname="tiro",
    )
    page.insert_text(
        (290, 824),
        "42",
        fontsize=10,
        fontname="tiro",
    )
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
    _, findings = _run_with_pdf(pdf_path)
    blocking = tuple(
        finding
        for finding in findings
        if finding.status is FindingStatus.FAIL and finding.severity.value == "error"
    )
    assert not blocking, [(item.rule_id, item.message) for item in blocking]
    assert formal_exit_code(findings) is ExitCode.SUCCESS


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


def test_tempora_body_headings_and_repeated_footer_pass_pdf_metrics(
    tmp_path: Path,
) -> None:
    pdf_path = _tempora_multipage_pdf(tmp_path / "tempora-multipage.pdf")
    bundle = PdfExtractor(tmp_path).extract(pdf_path)
    extracted_fonts = {span.font for span in bundle.spans}

    _, findings = _run_with_pdf(pdf_path)
    fmt01 = next(item for item in findings if item.rule_id == "FMT-01")
    fmt05 = next(item for item in findings if item.rule_id == "FMT-05")

    assert "Tempora-Regular" in extracted_fonts
    assert fmt01.status is FindingStatus.PASS
    assert fmt05.status is FindingStatus.PASS
    assert fmt01.evidence and fmt05.evidence
    assert "font_ratio=1.0000" in (fmt01.evidence[0].description or "")
    assert "repeated_footer" in (fmt05.evidence[0].description or "")


def test_fmt01_mixed_pdf_context_has_explainable_classification(
    tmp_path: Path,
) -> None:
    pdf_path = _fmt01_mixed_context_pdf(tmp_path / "fmt01-mixed-context.pdf")

    _, findings = _run_with_pdf(pdf_path)
    fmt01 = next(item for item in findings if item.rule_id == "FMT-01")
    evidence = " ".join(item.description or "" for item in fmt01.evidence)

    assert fmt01.status is FindingStatus.PASS
    assert "excluded=" in evidence
    assert "caption:" in evidence
    assert "heading:" in evidence
    assert "listing:" in evidence
    assert "table:" in evidence
    assert "retained=inline_code:" in evidence
    assert "top_sizes=" in evidence
    assert "mismatch_pages=" in evidence


def test_synthetic_body_margin_violation_has_geometric_evidence(
    tmp_path: Path,
) -> None:
    pdf_path = _margin_overflow_pdf(tmp_path / "body-margin-overflow.pdf")

    _, findings = _run_with_pdf(pdf_path)
    fmt05 = next(item for item in findings if item.rule_id == "FMT-05")

    assert fmt05.status is FindingStatus.FAIL
    assert fmt05.path == "body-margin-overflow.pdf"
    assert fmt05.page == 1
    assert fmt05.evidence
    description = fmt05.evidence[0].description or ""
    assert "bbox=[" in description
    assert "bounds=[" in description
    assert "overflow_pt=[" in description


@pytest.mark.parametrize("kind", ["image", "vector"])
def test_synthetic_graphic_margin_violation_still_fails(
    tmp_path: Path,
    kind: str,
) -> None:
    pdf_path = _graphic_overflow_pdf(tmp_path / f"{kind}-overflow.pdf", kind)

    _, findings = _run_with_pdf(pdf_path)
    fmt05 = next(item for item in findings if item.rule_id == "FMT-05")

    assert fmt05.status is FindingStatus.FAIL
    assert fmt05.evidence
    assert f"classification={kind}" in (fmt05.evidence[0].description or "")


@pytest.mark.parametrize("page_number", [1, 2], ids=["title-page", "ordinary-page"])
def test_vector_with_coordinate_noise_within_geometry_tolerance_passes(
    tmp_path: Path,
    page_number: int,
) -> None:
    pdf_path = _bounded_vector_pdf(
        tmp_path / f"frame-page-{page_number}.pdf",
        page_number=page_number,
        overflow_pt=0.3,
    )

    _, findings = _run_with_pdf(pdf_path)
    fmt05 = next(item for item in findings if item.rule_id == "FMT-05")

    assert fmt05.status is FindingStatus.PASS
    assert fmt05.evidence
    assert "geometry_tolerance_pt=0.50" in (fmt05.evidence[0].description or "")


@pytest.mark.parametrize("overflow_pt", [0.51, 1.7, 2.6])
def test_vector_above_geometry_tolerance_remains_formal_failure(
    tmp_path: Path,
    overflow_pt: float,
) -> None:
    pdf_path = _bounded_vector_pdf(
        tmp_path / f"vector-overflow-{overflow_pt}.pdf",
        page_number=1,
        overflow_pt=overflow_pt,
    )

    _, findings = _run_with_pdf(pdf_path)
    fmt05 = next(item for item in findings if item.rule_id == "FMT-05")

    assert fmt05.status is FindingStatus.FAIL
    assert fmt05.evidence
    description = fmt05.evidence[0].description or ""
    assert "delta_pt=" in description
    assert "geometry_tolerance_pt=0.50" in description


def test_long_table_overflow_near_footer_and_page_number_remains_failure(
    tmp_path: Path,
) -> None:
    pdf_path = _long_table_footer_overflow_pdf(
        tmp_path / "long-table-footer-overflow.pdf",
        overflow_pt=2.6,
    )

    _, findings = _run_with_pdf(pdf_path)
    fmt05 = next(item for item in findings if item.rule_id == "FMT-05")

    assert fmt05.status is FindingStatus.FAIL
    assert fmt05.page == 1
    assert fmt05.evidence
    description = fmt05.evidence[0].description or ""
    assert "delta_pt=2.60" in description
    assert "geometry_tolerance_pt=0.50" in description
