"""Unit tests for FMT formatting rules."""

from __future__ import annotations

from pathlib import Path

from normocontrol.domain import FindingStatus
from normocontrol.extract.base import (
    BoundingBox,
    DocumentBundle,
    ExtractionQuality,
    PageInfo,
    SourceFile,
    SourceFormat,
    TextSpan,
    sha256_text,
)
from normocontrol.rules._pdf_metrics import is_times_new_roman, span_is_bold
from normocontrol.rules.context import LatexProject
from normocontrol.rules.formatting import (
    Fmt01BodyFontRule,
    Fmt02HeadingBoldRule,
    Fmt03LineSpacingRule,
    Fmt04ParindentRule,
    Fmt05MarginsRule,
    class_file_text,
)

from .helpers import effective_rule, execution_context, minimal_rubric


def _span(
    *,
    text: str = "sample",
    page: int = 1,
    font: str = "Times-Roman",
    font_size: float = 14.0,
    flags: int | None = None,
    x0: float = 100.0,
    y0: float = 100.0,
) -> TextSpan:
    return TextSpan(
        text=text,
        page=page,
        char_start=0,
        char_end=len(text),
        font=font,
        font_size=font_size,
        flags=flags,
        bbox=BoundingBox(x0=x0, y0=y0, x1=x0 + 80, y1=y0 + 14),
    )


def _context_with_cls(tmp_path: Path, cls_text: str, *, bundle: DocumentBundle | None = None):
    project = tmp_path / "project"
    project.mkdir()
    (project / "gostcheck-vkr.cls").write_text(cls_text, encoding="utf-8")
    (project / "protected-files.yaml").write_text(
        "version: 1\nclass_files:\n  - path: gostcheck-vkr.cls\n    sha256: "
        + "a" * 64
        + "\nallowed_renewcommand: []\n",
        encoding="utf-8",
    )
    (project / "main.tex").write_text("\\documentclass{gostcheck-vkr}\n", encoding="utf-8")
    rubric = minimal_rubric(effective_rule("FMT-04", layer="class"))
    return execution_context(
        rubric,
        bundle=bundle,
        latex=LatexProject(root=project, main_tex=project / "main.tex"),
    )


GOOD_CLS = """\
\\RequirePackage{fontspec}
\\setmainfont{Times New Roman}
\\RequirePackage{titlesec}
\\onehalfspacing
\\setlength{\\parindent}{12.5mm}
\\RequirePackage[left=30mm,right=10mm,top=20mm,bottom=20mm]{geometry}
"""


def _pdf_bundle(
    *raw_spans: TextSpan,
    pages: tuple[PageInfo, ...] = (),
    warnings: tuple[str, ...] = (),
) -> DocumentBundle:
    offset = 0
    spans: list[TextSpan] = []
    text_parts: list[str] = []
    for span in raw_spans:
        spans.append(
            span.model_copy(
                update={
                    "char_start": offset,
                    "char_end": offset + len(span.text),
                }
            )
        )
        text_parts.append(span.text)
        offset += len(span.text)
    text = "".join(text_parts)
    return DocumentBundle(
        source_format=SourceFormat.PDF,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=(
            ExtractionQuality.DEGRADED
            if "PDF_NO_TEXT_LAYER" in warnings
            else ExtractionQuality.HIGH
        ),
        source_files=(SourceFile(path="doc.pdf", sha256="a" * 64),),
        spans=tuple(spans),
        pages=pages,
        sections=(),
        chunks=(),
        warnings=warnings,
    )


def _pdf_context(rule_id: str, bundle: DocumentBundle):
    rubric = minimal_rubric(effective_rule(rule_id, layer="class"))
    return execution_context(rubric, bundle=bundle, pdf_path=Path("doc.pdf"))


def test_pdf_metric_helpers() -> None:
    assert is_times_new_roman("TimesNewRomanPSMT")
    assert span_is_bold(_span(flags=16))
    assert span_is_bold(_span(font="Times-Bold"))


def test_fmt04_passes_with_expected_parindent(tmp_path: Path) -> None:
    context = _context_with_cls(tmp_path, GOOD_CLS)
    rule = effective_rule("FMT-04", layer="class")
    outcome = Fmt04ParindentRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.PASS


def test_fmt04_fails_without_parindent(tmp_path: Path) -> None:
    context = _context_with_cls(tmp_path, "\\LoadClass{article}\n")
    rule = effective_rule("FMT-04", layer="class")
    outcome = Fmt04ParindentRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.FAIL


def test_fmt01_pdf_leg_detects_wrong_font(tmp_path: Path) -> None:
    text = "Synthetic PDF body"
    bundle = DocumentBundle(
        source_format=SourceFormat.PDF,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="doc.pdf", sha256="a" * 64),),
        spans=(_span(font="Helvetica", font_size=14.0),),
        sections=(),
        chunks=(),
    )
    context = _context_with_cls(tmp_path, GOOD_CLS, bundle=bundle)
    rule = effective_rule("FMT-01", layer="class")
    outcome = Fmt01BodyFontRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.FAIL


def test_class_file_text_reads_protected_cls(tmp_path: Path) -> None:
    context = _context_with_cls(tmp_path, GOOD_CLS)
    assert "fontspec" in (class_file_text(context) or "")


def test_fmt05_pdf_leg_flags_margin_overflow(tmp_path: Path) -> None:
    text = "Synthetic"
    bundle = DocumentBundle(
        source_format=SourceFormat.PDF,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="doc.pdf", sha256="a" * 64),),
        spans=(_span(x0=10.0, y0=10.0),),
        pages=(PageInfo(number=1, width=595.0, height=842.0, rotation=0),),
        sections=(),
        chunks=(),
    )
    context = _context_with_cls(tmp_path, GOOD_CLS, bundle=bundle)
    rule = effective_rule("FMT-05", layer="class")
    outcome = Fmt05MarginsRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.FAIL


def test_fmt01_pdf_only_accepts_postscript_times_name() -> None:
    bundle = _pdf_bundle(_span(font="TimesNewRomanPSMT"))
    outcome = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", bundle),
        effective_rule("FMT-01", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.PASS


def test_empty_pdf_spans_are_unverifiable() -> None:
    bundle = _pdf_bundle(warnings=("PDF_NO_TEXT_LAYER",))
    outcome = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", bundle),
        effective_rule("FMT-01", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE
    assert "PDF text layer" in outcome.findings[0].message


def test_fmt02_pdf_only_without_heading_is_unverifiable() -> None:
    bundle = _pdf_bundle(_span(text="ordinary body", font_size=14.0))
    outcome = Fmt02HeadingBoldRule().run(
        _pdf_context("FMT-02", bundle),
        effective_rule("FMT-02", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE


def test_fmt03_handles_aligned_two_column_text() -> None:
    spans = tuple(
        _span(text=f"left {index}", x0=100.0, y0=100.0 + index * 21) for index in range(4)
    ) + tuple(_span(text=f"right {index}", x0=330.0, y0=100.0 + index * 21) for index in range(4))
    bundle = _pdf_bundle(*spans)
    outcome = Fmt03LineSpacingRule().run(
        _pdf_context("FMT-03", bundle),
        effective_rule("FMT-03", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.PASS


def test_fmt04_pdf_only_message_states_measurement_limit() -> None:
    bundle = _pdf_bundle(_span())
    outcome = Fmt04ParindentRule().run(
        _pdf_context("FMT-04", bundle),
        effective_rule("FMT-04", layer="class"),
    )

    finding = outcome.findings[0]
    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "нельзя надёжно доказать" in finding.message
    assert "PDF" in finding.message


def test_fmt05_accepts_rotated_page_coordinates() -> None:
    page = PageInfo(number=1, width=842.0, height=595.0, rotation=90)
    bundle = _pdf_bundle(_span(x0=100.0, y0=105.0), pages=(page,))
    outcome = Fmt05MarginsRule().run(
        _pdf_context("FMT-05", bundle),
        effective_rule("FMT-05", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.PASS


def test_fmt05_ignores_page_without_body_spans_after_measurable_page() -> None:
    pages = (
        PageInfo(number=1, width=595.0, height=842.0, rotation=0),
        PageInfo(number=2, width=595.0, height=842.0, rotation=0),
    )
    bundle = _pdf_bundle(
        _span(text="body text", page=1, x0=100.0, y0=100.0),
        _span(text="x", page=2, x0=1.0, y0=1.0),
        pages=pages,
    )
    outcome = Fmt05MarginsRule().run(
        _pdf_context("FMT-05", bundle),
        effective_rule("FMT-05", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.PASS
