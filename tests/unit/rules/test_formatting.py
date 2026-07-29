"""Unit tests for FMT formatting rules."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from normocontrol.rules._pdf_metrics import (
    bbox_within_margins,
    font_size_match_ratio,
    is_times_new_roman,
    margin_bounds,
    select_body_spans,
    significant_character_count,
    span_is_bold,
    times_new_roman_ratio,
)
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
    x1: float | None = None,
    y1: float | None = None,
) -> TextSpan:
    return TextSpan(
        text=text,
        page=page,
        char_start=0,
        char_end=len(text),
        font=font,
        font_size=font_size,
        flags=flags,
        bbox=BoundingBox(
            x0=x0,
            y0=y0,
            x1=x0 + 80 if x1 is None else x1,
            y1=y0 + 14 if y1 is None else y1,
        ),
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


@pytest.mark.parametrize(
    "font",
    [
        "ABCDEF+TimesNewRomanPSMT",
        "Times New Roman",
        "Times-Roman",
        "Tempora-Regular",
        "TimesNewRomanPS-BoldMT",
        "Times-Italic",
        "Tempora-Bold",
        "Tempora-Italic",
        "TeXGyreTermes-Regular",
        "ABCDEF+TeXGyreTermes-Bold",
        "TeX Gyre Termes Italic",
        "TeXGyreTermes-BoldItalic",
        "ABCDEF+LiberationSerif-Regular",
        "Liberation Serif Bold",
        "LiberationSerif-Italic",
        "LiberationSerif-BoldItalic",
    ],
)
def test_times_compatible_aliases_are_explicit(font: str) -> None:
    assert is_times_new_roman(font)


def test_tempora_requires_an_explicit_alias() -> None:
    assert is_times_new_roman("Tempora-Regular")
    assert not is_times_new_roman(
        "Tempora-Regular",
        aliases={"Times New Roman", "TimesNewRomanPSMT", "Times-Roman"},
    )


@pytest.mark.parametrize(
    "font",
    ["Helvetica", "Arial", "DejaVuSerif", "Bookman-Serif"],
)
def test_non_alias_fonts_are_not_times_compatible(font: str) -> None:
    assert not is_times_new_roman(font)


def test_character_weighted_ratios_do_not_depend_on_span_splitting() -> None:
    whole = (
        _span(text="abcdefgh", font="Times-Roman", font_size=14.0),
        _span(text="ij", font="Helvetica", font_size=12.0),
    )
    split = (
        *(_span(text=char, font="Times-Roman", font_size=14.0) for char in "abcdefgh"),
        *(_span(text=char, font="Helvetica", font_size=12.0) for char in "ij"),
    )

    assert times_new_roman_ratio(whole) == pytest.approx(0.8)
    assert times_new_roman_ratio(split) == pytest.approx(0.8)
    assert font_size_match_ratio(whole, expected_pt=14.0) == pytest.approx(0.8)
    assert font_size_match_ratio(split, expected_pt=14.0) == pytest.approx(0.8)
    selection = select_body_spans(split, ())
    assert selection.significant_chars == 10
    assert len(selection.spans) == 10


def test_fmt01_excludes_heading_and_code_from_body_ratio() -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    body = _span(
        text="Synthetic body text with enough significant characters for the metric.",
        font="Times-Roman",
        font_size=14.0,
        y0=150.0,
    )
    heading = _span(text="Heading", font="Helvetica", font_size=16.0, y0=100.0)
    code = tuple(
        _span(
            text=text,
            font="Courier",
            font_size=10.0,
            y0=200.0 + index * 14.0,
        )
        for index, text in enumerate(("for item in values:", "    print(item)", "    return item"))
    )
    bundle = _pdf_bundle(heading, body, *code, pages=(page,))

    selection = select_body_spans(bundle.spans, bundle.pages)
    outcome = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", bundle),
        effective_rule("FMT-01", layer="class"),
    )

    assert selection.spans == (bundle.spans[1],)
    assert outcome.findings[0].status is FindingStatus.PASS


def test_fmt01_characterization_keeps_ordinary_14pt_body() -> None:
    body = _span(
        text="Ordinary synthetic paragraph in the expected font and size.",
        font="Times-Roman",
        font_size=14.0,
    )

    selection = select_body_spans((body,), ())

    assert selection.spans == (body,)
    assert selection.significant_chars == significant_character_count(body.text)
    assert selection.excluded_chars == ()


def test_fmt01_characterization_keeps_ordinary_12pt_body_and_lowers_ratio() -> None:
    body = _span(
        text="Ordinary synthetic paragraph using a nonconforming twelve point size.",
        font="Times-Roman",
        font_size=12.0,
    )

    selection = select_body_spans((body,), ())

    assert selection.spans == (body,)
    assert font_size_match_ratio(selection.spans, expected_pt=14.0) == 0.0


def test_fmt01_inline_bold_times_variant_stays_compatible_body() -> None:
    spans = (
        _span(text="Ordinary body with ", x0=100.0, x1=220.0),
        _span(
            text="emphasis",
            font="Tempora-Bold",
            flags=20,
            x0=220.0,
            x1=280.0,
        ),
        _span(text=" retained in the measured line.", x0=280.0, x1=470.0),
    )

    selection = select_body_spans(spans, ())

    assert selection.spans == spans
    assert times_new_roman_ratio(selection.spans) == 1.0


def test_fmt01_characterization_excludes_large_confirmed_heading() -> None:
    body = _span(
        text="Ordinary synthetic paragraph with enough text to establish body size.",
        font="Times-Roman",
        font_size=14.0,
        y0=140.0,
    )
    heading = _span(
        text="Synthetic heading",
        font="Helvetica",
        font_size=18.0,
        y0=90.0,
    )

    selection = select_body_spans((body, heading), ())

    assert selection.spans == (body,)
    assert dict(selection.excluded_chars)["heading"] == significant_character_count(heading.text)


def test_fmt01_excludes_isolated_full_bold_heading_at_body_size() -> None:
    spans = (
        _span(
            text="Synthetic bold section heading",
            font="Tempora-Bold",
            font_size=14.0,
            flags=20,
            y0=80.0,
        ),
        _span(
            text="Ordinary body line one with enough text for measurement.",
            y0=122.0,
        ),
        _span(
            text="Ordinary body line two with enough text for measurement.",
            y0=143.0,
        ),
    )

    selection = select_body_spans(spans, ())

    assert selection.spans == spans[1:]
    assert dict(selection.excluded_chars)["heading"] == significant_character_count(spans[0].text)


def test_fmt01_characterization_excludes_caption_and_repeated_footer() -> None:
    pages = (
        PageInfo(number=1, width=595.0, height=842.0, rotation=0),
        PageInfo(number=2, width=595.0, height=842.0, rotation=0),
    )
    spans = (
        _span(text="Body page one remains measurable.", page=1, y0=140.0),
        _span(text="Рисунок 1 — Synthetic caption", page=1, font_size=10.0, y0=500.0),
        _span(text="Synthetic repeated footer", page=1, font_size=10.0, y0=810.0),
        _span(text="Body page two remains measurable.", page=2, y0=140.0),
        _span(text="Synthetic repeated footer", page=2, font_size=10.0, y0=810.0),
    )

    selection = select_body_spans(spans, pages)
    excluded = dict(selection.excluded_chars)

    assert selection.spans == (spans[0], spans[3])
    assert excluded["caption"] == significant_character_count(spans[1].text)
    assert excluded["repeated_footer"] == 2 * significant_character_count(spans[2].text)


def test_fmt01_multiline_monospace_listing_is_excluded_by_context() -> None:
    body = _span(
        text="Ordinary synthetic paragraph remains in the body population.",
        y0=120.0,
    )
    listing = tuple(
        _span(
            text=text,
            font="SFTT1200",
            font_size=12.0,
            x0=110.0,
            y0=200.0 + index * 15.0,
        )
        for index, text in enumerate(
            (
                "def calculate(value):",
                "    result = value + 1",
                "    return result",
            )
        )
    )

    selection = select_body_spans((body, *listing), ())

    assert selection.spans == (body,)
    assert dict(selection.excluded_chars)["listing"] == sum(
        significant_character_count(span.text) for span in listing
    )


def test_fmt01_short_inline_monospace_is_retained_with_diagnostic() -> None:
    spans = (
        _span(text="Use ", x0=100.0, x1=130.0, y0=140.0),
        _span(
            text="value_name",
            font="Courier",
            font_size=14.0,
            x0=130.0,
            x1=205.0,
            y0=140.0,
        ),
        _span(text=" in this ordinary sentence.", x0=205.0, x1=380.0, y0=140.0),
    )

    selection = select_body_spans(spans, ())

    assert selection.spans == spans
    assert dict(selection.retained_chars)["inline_code"] == significant_character_count(
        spans[1].text
    )
    assert "listing" not in dict(selection.excluded_chars)


def test_fmt01_formula_context_excludes_computer_modern_line() -> None:
    body = _span(
        text="Ordinary synthetic paragraph remains measurable.",
        y0=140.0,
    )
    formula = (
        _span(text="x", font="CMMI12", x0=220.0, x1=230.0, y0=220.0),
        _span(text="=", font="CMR12", x0=232.0, x1=242.0, y0=220.0),
        _span(text="y", font="CMMI12", x0=244.0, x1=254.0, y0=220.0),
        _span(text="+", font="CMSY10", font_size=10.0, x0=256.0, x1=264.0, y0=223.0),
        _span(text="1", font="CMR12", x0=266.0, x1=276.0, y0=220.0),
    )

    selection = select_body_spans((body, *formula), ())

    assert selection.spans == (body,)
    assert dict(selection.excluded_chars)["formula"] == sum(
        significant_character_count(span.text) for span in formula
    )


def test_fmt01_ordinary_computer_modern_without_math_context_stays_body() -> None:
    body = _span(
        text="Ordinary prose set in Computer Modern remains a body violation.",
        font="CMR12",
        font_size=14.0,
    )

    selection = select_body_spans((body,), ())

    assert selection.spans == (body,)
    assert dict(selection.retained_chars)["unconfirmed_math"] == significant_character_count(
        body.text
    )


def test_fmt01_math_font_name_without_formula_context_stays_body() -> None:
    span = _span(
        text="variable",
        font="CMMI12",
        font_size=14.0,
    )

    selection = select_body_spans((span,), ())

    assert selection.spans == (span,)
    assert dict(selection.retained_chars)["unconfirmed_math"] == significant_character_count(
        span.text
    )


def test_fmt01_mixed_page_excludes_table_formula_and_listing_only() -> None:
    body = _span(
        text="Ordinary synthetic body is the only measured paragraph.",
        y0=120.0,
    )
    table = (
        _span(text="Metric", font_size=10.0, x0=100.0, x1=150.0, y0=180.0),
        _span(text="Value", font_size=10.0, x0=300.0, x1=340.0, y0=180.0),
        _span(text="Alpha", font_size=10.0, x0=100.0, x1=145.0, y0=195.0),
        _span(text="10", font_size=10.0, x0=300.0, x1=315.0, y0=195.0),
        _span(text="Beta", font_size=10.0, x0=100.0, x1=140.0, y0=210.0),
        _span(text="20", font_size=10.0, x0=300.0, x1=315.0, y0=210.0),
    )
    formula = (
        _span(text="a", font="CMMI12", x0=220.0, x1=230.0, y0=260.0),
        _span(text="=", font="CMR12", x0=232.0, x1=242.0, y0=260.0),
        _span(text="b", font="CMMI12", x0=244.0, x1=254.0, y0=260.0),
    )
    listing = tuple(
        _span(
            text=text,
            font="Courier",
            font_size=10.0,
            x0=110.0,
            y0=310.0 + index * 14.0,
        )
        for index, text in enumerate(("if ready:", "    run()", "    return 0"))
    )

    selection = select_body_spans((body, *table, *formula, *listing), ())
    excluded = dict(selection.excluded_chars)

    assert selection.spans == (body,)
    assert excluded["table"] == sum(significant_character_count(span.text) for span in table)
    assert excluded["formula"] == sum(significant_character_count(span.text) for span in formula)
    assert excluded["listing"] == sum(significant_character_count(span.text) for span in listing)


def test_fmt01_invalid_bbox_is_counted_and_never_hidden() -> None:
    invalid = _span(text="Damaged synthetic body").model_copy(
        update={"bbox": BoundingBox(x0=100.0, y0=100.0, x1=100.0, y1=114.0)}
    )

    selection = select_body_spans((invalid,), ())

    assert selection.spans == ()
    assert selection.invalid_bbox_count == 1
    assert dict(selection.excluded_chars)["invalid_bbox"] == significant_character_count(
        invalid.text
    )


def test_fmt01_insufficient_matching_body_is_unverifiable_not_pass() -> None:
    bundle = _pdf_bundle(_span(text="tiny", font="Times-Roman", font_size=14.0))

    outcome = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", bundle),
        effective_rule("FMT-01", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE
    assert "insufficient_body_text" in (outcome.findings[0].evidence[0].description or "")


@pytest.mark.parametrize(
    ("matching_chars", "expected_status"),
    (
        (95, FindingStatus.PASS),
        (94, FindingStatus.FAIL),
        (96, FindingStatus.PASS),
    ),
    ids=("exactly-95-percent", "below-95-percent", "above-95-percent"),
)
def test_fmt01_enforces_unchanged_95_percent_boundary(
    matching_chars: int,
    expected_status: FindingStatus,
) -> None:
    mismatching_chars = 100 - matching_chars
    spans = (
        _span(text="a" * matching_chars, font="Times-Roman", font_size=14.0, y0=120.0),
        _span(text="b" * mismatching_chars, font="Helvetica", font_size=12.0, y0=140.0),
    )
    bundle = _pdf_bundle(*spans)

    outcome = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", bundle),
        effective_rule("FMT-01", layer="class"),
    )

    assert outcome.findings[0].status is expected_status


def test_fmt01_span_permutation_preserves_selection_and_evidence() -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    spans = (
        _span(text="a" * 95, font="Times-Roman", font_size=14.0, y0=120.0),
        _span(text="b" * 5, font="Helvetica", font_size=12.0, y0=140.0),
        _span(text="Synthetic heading", font="Helvetica", font_size=18.0, y0=80.0),
    )
    first_bundle = _pdf_bundle(*spans, pages=(page,))
    second_bundle = _pdf_bundle(*reversed(spans), pages=(page,))

    first_selection = select_body_spans(first_bundle.spans, first_bundle.pages)
    second_selection = select_body_spans(second_bundle.spans, second_bundle.pages)
    first = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", first_bundle),
        effective_rule("FMT-01", layer="class"),
    )
    second = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", second_bundle),
        effective_rule("FMT-01", layer="class"),
    )

    assert first_selection.significant_chars == second_selection.significant_chars
    assert first_selection.excluded_chars == second_selection.excluded_chars
    assert first.findings[0].model_dump() == second.findings[0].model_dump()


def test_fmt01_evidence_explains_denominators_distributions_and_exclusions() -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    body = _span(
        text="Expected synthetic body paragraph with enough measurable characters.",
        y0=120.0,
    )
    mismatch = _span(
        text="wrong-size",
        font="Helvetica",
        font_size=12.0,
        y0=145.0,
    )
    listing = tuple(
        _span(
            text=text,
            font="Courier",
            font_size=10.0,
            y0=200.0 + index * 14.0,
        )
        for index, text in enumerate(("for item in values:", "    use(item)", "    return"))
    )
    bundle = _pdf_bundle(body, mismatch, *listing, pages=(page,))

    outcome = Fmt01BodyFontRule().run(
        _pdf_context("FMT-01", bundle),
        effective_rule("FMT-01", layer="class"),
    )
    evidence = tuple(item.description or "" for item in outcome.findings[0].evidence)
    combined = " ".join(evidence)

    assert all(len(item) <= 240 for item in evidence)
    assert "body_chars=" in combined
    assert "font_denominator=" in combined
    assert "size_denominator=" in combined
    assert "top_fonts=" in combined
    assert "top_sizes=" in combined
    assert "excluded=" in combined
    assert "mismatch_pages=" in combined
    assert "invalid_bbox=" in combined
    assert "sha256:" in combined


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


@pytest.mark.parametrize(
    ("delta_pt", "expected"),
    [
        (0.0, True),
        (0.3, True),
        (0.5, True),
        (0.51, False),
        (1.7, False),
        (2.6, False),
    ],
)
def test_fmt05_geometry_tolerance_boundary_is_deterministic(
    delta_pt: float,
    expected: bool,
) -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    left, _, top, _ = margin_bounds(page)
    bbox = BoundingBox(
        x0=left - delta_pt,
        y0=top + 10.0,
        x1=left + 100.0,
        y1=top + 24.0,
    )

    assert bbox_within_margins(bbox, page, geometry_tolerance_pt=0.5) is expected


def test_fmt05_geometry_tolerance_handles_float_rounding_at_boundary() -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    left, _, top, _ = margin_bounds(page)
    bbox = BoundingBox(
        x0=left - (0.1 + 0.2),
        y0=top + 10.0,
        x1=left + 100.0,
        y1=top + 24.0,
    )

    assert bbox_within_margins(bbox, page, geometry_tolerance_pt=0.3)


@pytest.mark.parametrize(
    ("label", "delta_pt"),
    [
        ("ordinary text", 1.7),
        ("formula E = mc^2", 1.7),
    ],
)
def test_fmt05_body_and_formula_above_tolerance_keep_formal_failure(
    label: str,
    delta_pt: float,
) -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    left, _, top, _ = margin_bounds(page)
    bundle = _pdf_bundle(
        _span(
            text=label,
            x0=left - delta_pt,
            y0=top + 20.0,
            x1=left + 100.0,
            y1=top + 34.0,
        ),
        pages=(page,),
    )

    finding = (
        Fmt05MarginsRule()
        .run(
            _pdf_context("FMT-05", bundle),
            effective_rule("FMT-05", layer="class"),
        )
        .findings[0]
    )

    assert finding.status is FindingStatus.FAIL
    assert finding.evidence
    description = finding.evidence[0].description or ""
    assert "delta_pt=1.70" in description
    assert "geometry_tolerance_pt=0.50" in description


def test_fmt05_zero_delta_pass_evidence_is_auditable() -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    bundle = _pdf_bundle(
        _span(text="Ordinary body text", x0=100.0, y0=120.0),
        pages=(page,),
    )

    finding = (
        Fmt05MarginsRule()
        .run(
            _pdf_context("FMT-05", bundle),
            effective_rule("FMT-05", layer="class"),
        )
        .findings[0]
    )

    assert finding.status is FindingStatus.PASS
    assert finding.evidence
    description = finding.evidence[0].description or ""
    assert "delta_pt=0.00" in description
    assert "bbox=[" in description
    assert "bounds=[" in description


def test_fmt01_pdf_only_accepts_postscript_times_name() -> None:
    bundle = _pdf_bundle(
        _span(
            text="Synthetic body text with a sufficient deterministic sample.",
            font="TimesNewRomanPSMT",
        )
    )
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


@pytest.mark.parametrize("rule_id", ["FMT-01", "FMT-05"])
def test_zero_bbox_never_produces_pass(rule_id: str) -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    zero_bbox = _span(text="Synthetic body").model_copy(
        update={"bbox": BoundingBox(x0=100.0, y0=100.0, x1=100.0, y1=100.0)}
    )
    bundle = _pdf_bundle(zero_bbox, pages=(page,))
    implementation = Fmt01BodyFontRule() if rule_id == "FMT-01" else Fmt05MarginsRule()

    outcome = implementation.run(
        _pdf_context(rule_id, bundle),
        effective_rule(rule_id, layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE
    assert outcome.findings[0].evidence


def test_fmt05_ignores_single_page_number_in_footer_zone() -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    bundle = _pdf_bundle(
        _span(text="Synthetic body text", y0=120.0),
        _span(text="1", x0=290.0, x1=300.0, y0=810.0, y1=824.0),
        pages=(page,),
    )

    outcome = Fmt05MarginsRule().run(
        _pdf_context("FMT-05", bundle),
        effective_rule("FMT-05", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.PASS


def test_fmt05_ignores_repeated_footer_but_not_the_whole_footer_zone() -> None:
    pages = (
        PageInfo(number=1, width=595.0, height=842.0, rotation=0),
        PageInfo(number=2, width=595.0, height=842.0, rotation=0),
    )
    bundle = _pdf_bundle(
        _span(text="Body page one", page=1, y0=120.0),
        _span(text="Synthetic department footer 2026", page=1, x0=30.0, y0=800.0),
        _span(text="Body page two", page=2, y0=120.0),
        _span(text="Synthetic department footer 2026", page=2, x0=30.0, y0=800.0),
        pages=pages,
    )

    outcome = Fmt05MarginsRule().run(
        _pdf_context("FMT-05", bundle),
        effective_rule("FMT-05", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.PASS
    assert "repeated_footer" in (outcome.findings[0].evidence[0].description or "")


@pytest.mark.parametrize(
    ("x0", "y0", "x1", "y1"),
    [
        (10.0, 120.0, 150.0, 134.0),
        (500.0, 120.0, 590.0, 134.0),
        (100.0, 10.0, 240.0, 24.0),
        (100.0, 800.0, 240.0, 814.0),
    ],
    ids=["left", "right", "top", "bottom"],
)
def test_fmt05_fails_for_body_text_beyond_each_margin(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    bundle = _pdf_bundle(
        _span(
            text="Ordinary synthetic body text",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
        ),
        pages=(page,),
    )

    outcome = Fmt05MarginsRule().run(
        _pdf_context("FMT-05", bundle),
        effective_rule("FMT-05", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.FAIL


def test_footer_like_text_inside_body_is_not_excluded() -> None:
    pages = (
        PageInfo(number=1, width=595.0, height=842.0, rotation=0),
        PageInfo(number=2, width=595.0, height=842.0, rotation=0),
    )
    bundle = _pdf_bundle(
        _span(text="Synthetic footer", page=1, x0=10.0, y0=200.0),
        _span(text="Synthetic footer", page=2, x0=10.0, y0=200.0),
        pages=pages,
    )

    outcome = Fmt05MarginsRule().run(
        _pdf_context("FMT-05", bundle),
        effective_rule("FMT-05", layer="class"),
    )

    assert outcome.findings[0].status is FindingStatus.FAIL


def test_fmt_evidence_contains_location_and_numeric_metrics() -> None:
    page = PageInfo(number=1, width=595.0, height=842.0, rotation=0)
    bundle = _pdf_bundle(
        _span(text="Ordinary body beyond left margin", x0=10.0, y0=120.0),
        pages=(page,),
    )

    finding = (
        Fmt05MarginsRule()
        .run(
            _pdf_context("FMT-05", bundle),
            effective_rule("FMT-05", layer="class"),
        )
        .findings[0]
    )

    assert finding.rule_id == "FMT-05"
    assert finding.path == "doc.pdf"
    assert finding.page == 1
    assert finding.evidence
    assert "bbox=" in finding.evidence[0].locator
    description = finding.evidence[0].description or ""
    assert "rule_id=FMT-05" in description
    assert "bounds=[" in description
    assert "overflow_pt=[" in description
