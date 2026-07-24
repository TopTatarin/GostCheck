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
