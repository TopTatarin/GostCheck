"""FMT-01..05 PDF formatting and class-file rules."""

from __future__ import annotations

import re

from normocontrol.domain import Evidence, FindingStatus, RuleLayer
from normocontrol.extract.base import BoundingBox, TextSpan
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._class_text import class_file_text
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules._pdf_metrics import (
    MARGINS_MM,
    bbox_margin_overflow,
    check_body_margins,
    check_layout_object_margins,
    example_pages,
    extract_pdf_layout_objects,
    font_size_match_ratio,
    heading_spans,
    median_line_spacing_ratio,
    page_text_bbox,
    select_body_spans,
    span_is_bold,
    times_new_roman_ratio,
    top_font_sizes,
    top_fonts,
    typography_mismatch_pages,
    typography_mismatch_samples,
)
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind

_FONT_SIZE_TOLERANCE_PT = 0.5
_BODY_FONT_RATIO_MIN = 0.95
_BODY_TEXT_MIN_CHARS = 20
_LINE_SPACING_TARGET = 1.5
_LINE_SPACING_TOLERANCE = 0.10


def effective_font_size_pt(context: ExecutionContext) -> float:
    """Resolve approved font size from config with rubric defaults."""
    override = context.config.params.font_size_pt
    default = context.rubric.meta.params_to_approve.font_size_pt
    return float(override if override is not None else default)


def effective_geometry_tolerance_pt(context: ExecutionContext) -> float:
    """Resolve approved PDF coordinate tolerance from config and rubric."""
    override = context.config.params.geometry_tolerance_pt
    default = context.rubric.meta.params_to_approve.geometry_tolerance_pt
    return float(override if override is not None else default)


def pdf_metrics_available(context: ExecutionContext) -> bool:
    """Return whether a PDF bundle exposes a usable text layer."""
    return context.has_pdf_text_layer


def _pass(
    rule: EffectiveRule,
    message: str,
    *,
    path: str | None = None,
    page: int | None = None,
    evidence: tuple[Evidence, ...] = (),
) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.PASS,
                message=message,
                path=path,
                page=page,
                evidence=evidence,
            ),
        )
    )


def _fail(
    rule: EffectiveRule,
    message: str,
    *,
    path: str | None = None,
    page: int | None = None,
    evidence: tuple[Evidence, ...] = (),
) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.FAIL,
                message=message,
                path=path,
                page=page,
                evidence=evidence,
            ),
        )
    )


def _unverifiable(
    rule: EffectiveRule,
    message: str,
    *,
    path: str | None = None,
    page: int | None = None,
    evidence: tuple[Evidence, ...] = (),
) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.UNVERIFIABLE,
                message=message,
                path=path,
                page=page,
                evidence=evidence,
            ),
        )
    )


def _pdf_source_path(context: ExecutionContext) -> str | None:
    bundle = context.pdf_metrics_bundle
    if bundle is None or not bundle.source_files:
        return None
    return bundle.source_files[0].path


def _bbox_value(bbox: BoundingBox | None) -> str:
    if bbox is None:
        return "unavailable"
    return ",".join(f"{value:.1f}" for value in (bbox.x0, bbox.y0, bbox.x1, bbox.y1))


def _metric_evidence(
    rule_id: str,
    *,
    path: str | None,
    page: int | None,
    bbox: BoundingBox | None,
    description: str,
) -> tuple[Evidence, ...]:
    safe_path = path or "<pdf>"
    locator = (
        f"{rule_id}|{safe_path}|page={page if page is not None else 'unknown'}|"
        f"bbox={_bbox_value(bbox)}"
    )
    return (Evidence(locator=locator, description=description),)


def _fmt01_evidence(
    rule_id: str,
    *,
    path: str | None,
    page: int | None,
    bbox: BoundingBox | None,
    descriptions: tuple[tuple[str, str], ...],
) -> tuple[Evidence, ...]:
    safe_path = path or "<pdf>"
    base = (
        f"{rule_id}|{safe_path}|page={page if page is not None else 'unknown'}|"
        f"bbox={_bbox_value(bbox)}"
    )
    return tuple(
        Evidence(locator=f"{base}|kind={kind}", description=description)
        for kind, description in descriptions
    )


def _first_span_on_page(spans: tuple[TextSpan, ...], page: int | None) -> TextSpan | None:
    if page is None:
        return spans[0] if spans else None
    return next((span for span in spans if span.page == page), None)


def _combine_class_pdf(
    context: ExecutionContext,
    rule: EffectiveRule,
    *,
    class_ok: bool | None,
    pdf_ok: bool | None,
    pass_message: str,
    class_fail_message: str,
    pdf_fail_message: str,
    class_missing_message: str,
    pdf_missing_message: str,
    pdf_path: str | None = None,
    pdf_page: int | None = None,
    pdf_evidence: tuple[Evidence, ...] = (),
) -> RuleRunOutcome:
    class_required = context.latex is not None
    pdf_required = context.pdf_only
    if class_required and class_ok is False:
        return _fail(rule, class_fail_message)
    if pdf_ok is False:
        return _fail(
            rule,
            pdf_fail_message,
            path=pdf_path,
            page=pdf_page,
            evidence=pdf_evidence,
        )
    if class_required and class_ok is None:
        return _unverifiable(rule, class_missing_message)
    if pdf_required and pdf_ok is None:
        return _unverifiable(
            rule,
            pdf_missing_message,
            path=pdf_path,
            page=pdf_page,
            evidence=pdf_evidence,
        )
    return _pass(
        rule,
        pass_message,
        path=pdf_path,
        page=pdf_page,
        evidence=pdf_evidence,
    )


class Fmt01BodyFontRule:
    rule_id = "FMT-01"
    required_sources: frozenset[SourceKind] = frozenset()

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None or context.pdf_only

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context) if context.latex is not None else None
        class_ok = None
        if cls_text is not None:
            class_ok = (
                re.search(
                    r"\\RequirePackage\s*\{fontspec\}|\\usepackage\s*\{fontspec\}",
                    cls_text,
                )
                is not None
                and re.search(r"Times\s*New\s*Roman|TimesNewRoman", cls_text, re.IGNORECASE)
                is not None
            )
        pdf_ok: bool | None = None
        pdf_path = _pdf_source_path(context)
        pdf_page: int | None = None
        pdf_evidence: tuple[Evidence, ...] = ()
        pdf_missing_message = "PDF text layer недоступен для проверки шрифта"
        pdf_bundle = context.pdf_metrics_bundle
        if pdf_metrics_available(context):
            assert pdf_bundle is not None
            selection = select_body_spans(pdf_bundle.spans, pdf_bundle.pages)
            spans = selection.spans
            invalid_chars = dict(selection.excluded_chars).get("invalid_bbox", 0)
            if spans and selection.significant_chars >= 1:
                expected = effective_font_size_pt(context)
                tnr_ratio = times_new_roman_ratio(spans)
                size_ratio = font_size_match_ratio(
                    spans,
                    expected_pt=expected,
                    tolerance_pt=_FONT_SIZE_TOLERANCE_PT,
                )
                mismatch_pages = typography_mismatch_pages(
                    spans,
                    expected_pt=expected,
                    tolerance_pt=_FONT_SIZE_TOLERANCE_PT,
                )
                measured_pages = example_pages(spans)
                pdf_page = (
                    mismatch_pages[0][0]
                    if mismatch_pages
                    else (measured_pages[0] if measured_pages else spans[0].page)
                )
                bbox = page_text_bbox(spans, pdf_page)
                fonts = ",".join(f"{name[:32]}:{count}" for name, count in top_fonts(spans))
                sizes = ",".join(f"{size:.1f}:{count}" for size, count in top_font_sizes(spans))
                excluded = ",".join(f"{kind}:{count}" for kind, count in selection.excluded_chars)
                retained = ",".join(f"{kind}:{count}" for kind, count in selection.retained_chars)
                mismatch_page_text = ",".join(f"{page}:{count}" for page, count in mismatch_pages)
                samples = typography_mismatch_samples(
                    spans,
                    expected_pt=expected,
                    tolerance_pt=_FONT_SIZE_TOLERANCE_PT,
                    limit=2,
                )
                sample_text = ",".join(
                    f"p{page}@{_bbox_value(sample_bbox)}#sha256:{digest}"
                    for page, sample_bbox, digest in samples
                )
                total_with_invalid = selection.significant_chars + invalid_chars
                max_tnr_ratio = (
                    tnr_ratio * selection.significant_chars + invalid_chars
                ) / total_with_invalid
                max_size_ratio = (
                    size_ratio * selection.significant_chars + invalid_chars
                ) / total_with_invalid
                proven_failure = (
                    max_tnr_ratio < _BODY_FONT_RATIO_MIN or max_size_ratio < _BODY_FONT_RATIO_MIN
                )
                if proven_failure:
                    pdf_ok = False
                    diagnostic = "proven_failure"
                elif selection.invalid_bbox_count:
                    pdf_missing_message = (
                        "геометрия части body-spans ненадёжна; FMT-01 нельзя подтвердить"
                    )
                    diagnostic = "invalid_body_geometry"
                elif selection.significant_chars < _BODY_TEXT_MIN_CHARS:
                    pdf_missing_message = (
                        "недостаточно надёжного body text для подтверждения FMT-01"
                    )
                    diagnostic = "insufficient_body_text"
                else:
                    pdf_ok = (
                        tnr_ratio >= _BODY_FONT_RATIO_MIN and size_ratio >= _BODY_FONT_RATIO_MIN
                    )
                    diagnostic = "measured"
                descriptions: tuple[tuple[str, str], ...] = (
                    (
                        "summary",
                        f"rule_id={rule.id}; body_chars={selection.significant_chars}; "
                        f"font_ratio={tnr_ratio:.4f}; "
                        f"font_denominator={selection.significant_chars}; "
                        f"size_ratio={size_ratio:.4f}; "
                        f"size_denominator={selection.significant_chars}; "
                        f"expected_pt={expected:.1f}; threshold={_BODY_FONT_RATIO_MIN:.4f}; "
                        f"invalid_bbox={selection.invalid_bbox_count}; "
                        f"diagnostic={diagnostic}",
                    ),
                    (
                        "distribution",
                        f"top_fonts={fonts or 'none'}; top_sizes={sizes or 'none'}",
                    ),
                    (
                        "classification",
                        f"excluded={excluded or 'none'}; retained={retained or 'none'}",
                    ),
                    (
                        "mismatch_pages",
                        f"mismatch_pages={mismatch_page_text or 'none'}",
                    ),
                    (
                        "samples",
                        f"mismatch_samples={sample_text or 'none'}",
                    ),
                )
                pdf_evidence = _fmt01_evidence(
                    rule.id,
                    path=pdf_path,
                    page=pdf_page,
                    bbox=bbox,
                    descriptions=descriptions,
                )
            else:
                diagnostic_span = _first_span_on_page(pdf_bundle.spans, None)
                pdf_page = diagnostic_span.page if diagnostic_span is not None else None
                diagnostic_bbox = diagnostic_span.bbox if diagnostic_span is not None else None
                pdf_missing_message = "надёжные body-spans не найдены; проверка FMT-01 неполна"
                excluded = ",".join(f"{kind}:{count}" for kind, count in selection.excluded_chars)
                retained = ",".join(f"{kind}:{count}" for kind, count in selection.retained_chars)
                descriptions = (
                    (
                        "summary",
                        f"rule_id={rule.id}; body_chars=0; font_denominator=0; "
                        f"size_denominator=0; invalid_bbox={selection.invalid_bbox_count}; "
                        "diagnostic=no_reliable_body_spans",
                    ),
                    (
                        "classification",
                        f"excluded={excluded or 'none'}; retained={retained or 'none'}",
                    ),
                )
                pdf_evidence = _fmt01_evidence(
                    rule.id,
                    path=pdf_path,
                    page=pdf_page,
                    bbox=diagnostic_bbox,
                    descriptions=descriptions,
                )
        elif pdf_bundle is not None:
            pdf_page = pdf_bundle.pages[0].number if pdf_bundle.pages else None
            pdf_evidence = _fmt01_evidence(
                rule.id,
                path=pdf_path,
                page=pdf_page,
                bbox=None,
                descriptions=(
                    (
                        "summary",
                        f"rule_id={rule.id}; body_chars=0; font_denominator=0; "
                        "size_denominator=0; invalid_bbox=0; "
                        "diagnostic=pdf_text_layer_unavailable",
                    ),
                ),
            )
        return _combine_class_pdf(
            context,
            rule,
            class_ok=class_ok,
            pdf_ok=pdf_ok,
            pass_message="основной текст соответствует Times New Roman и кеглю",
            class_fail_message="класс не задаёт Times New Roman через fontspec",
            pdf_fail_message=(
                "менее 95% значимых символов body PDF-спанов соответствуют "
                "Times-compatible alias и ожидаемому кеглю"
            ),
            class_missing_message="защищённый .cls недоступен",
            pdf_missing_message=pdf_missing_message,
            pdf_path=pdf_path,
            pdf_page=pdf_page,
            pdf_evidence=pdf_evidence,
        )


class Fmt02HeadingBoldRule:
    rule_id = "FMT-02"
    required_sources: frozenset[SourceKind] = frozenset()

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None or context.pdf_only

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context) if context.latex is not None else None
        class_ok = (
            None
            if cls_text is None
            else re.search(
                r"\\RequirePackage\s*\{titlesec\}|\\usepackage\s*\{titlesec\}|\\titleformat\b",
                cls_text,
            )
            is not None
        )
        pdf_ok: bool | None = None
        if pdf_metrics_available(context):
            pdf_bundle = context.pdf_metrics_bundle
            assert pdf_bundle is not None
            headings = heading_spans(pdf_bundle.spans)
            if not headings:
                pdf_ok = None
            else:
                bold_ratio = sum(1 for span in headings if span_is_bold(span)) / len(headings)
                pdf_ok = bold_ratio >= _BODY_FONT_RATIO_MIN
        return _combine_class_pdf(
            context,
            rule,
            class_ok=class_ok,
            pdf_ok=pdf_ok,
            pass_message="заголовки используют полужирное начертание",
            class_fail_message="класс не настраивает titlesec/titleformat",
            pdf_fail_message="PDF-заголовки не содержат bold-спанов",
            class_missing_message="защищённый .cls недоступен",
            pdf_missing_message="PDF text layer недоступен для проверки заголовков",
        )


class Fmt03LineSpacingRule:
    rule_id = "FMT-03"
    required_sources: frozenset[SourceKind] = frozenset()

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None or context.pdf_only

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context) if context.latex is not None else None
        class_ok = None
        if cls_text is not None:
            class_ok = (
                re.search(r"\\onehalfspacing\b", cls_text) is not None
                or re.search(r"\\linespread\s*\{\s*1\.5\s*\}", cls_text) is not None
            )
        pdf_ok: bool | None = None
        if pdf_metrics_available(context):
            pdf_bundle = context.pdf_metrics_bundle
            assert pdf_bundle is not None
            ratio = median_line_spacing_ratio(pdf_bundle.spans)
            if ratio is None:
                pdf_ok = None
            else:
                low = _LINE_SPACING_TARGET * (1.0 - _LINE_SPACING_TOLERANCE)
                high = _LINE_SPACING_TARGET * (1.0 + _LINE_SPACING_TOLERANCE)
                pdf_ok = low <= ratio <= high
        return _combine_class_pdf(
            context,
            rule,
            class_ok=class_ok,
            pdf_ok=pdf_ok,
            pass_message="межстрочный интервал 1,5 подтверждён",
            class_fail_message="класс не задаёт \\onehalfspacing",
            pdf_fail_message="медиана межстрочного интервала вне 1,5±10%",
            class_missing_message="защищённый .cls недоступен",
            pdf_missing_message="PDF text layer недоступен для проверки интервала",
        )


class Fmt04ParindentRule:
    rule_id = "FMT-04"
    required_sources: frozenset[SourceKind] = frozenset()

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None or context.pdf_only

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        if context.latex is None:
            return _unverifiable(
                rule,
                "абзацный отступ 12,5 мм нельзя надёжно доказать по геометрии PDF",
            )
        cls_text = class_file_text(context)
        if cls_text is None:
            return _unverifiable(rule, "защищённый .cls недоступен")
        if re.search(
            r"\\parindent\s*=\s*12\.5\s*mm|\\setlength\s*\{\s*\\parindent\s*\}\s*\{\s*12\.5\s*mm\s*\}",
            cls_text,
            re.IGNORECASE,
        ):
            return _pass(rule, "абзацный отступ 12,5 мм задан в классе")
        return _fail(rule, "класс не задаёт \\parindent=12.5mm")


class Fmt05MarginsRule:
    rule_id = "FMT-05"
    required_sources: frozenset[SourceKind] = frozenset()

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None or context.pdf_only

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context) if context.latex is not None else None
        margin_pattern = (
            r"left\s*=\s*30\s*mm.*right\s*=\s*10\s*mm.*top\s*=\s*20\s*mm.*bottom\s*=\s*20\s*mm"
        )
        class_ok = (
            None
            if cls_text is None
            else re.search(margin_pattern, cls_text, re.IGNORECASE | re.DOTALL) is not None
        )
        pdf_ok: bool | None = None
        pdf_path = _pdf_source_path(context)
        pdf_page: int | None = None
        pdf_evidence: tuple[Evidence, ...] = ()
        pdf_missing_message = "PDF text layer недоступен для проверки полей"
        pdf_bundle = context.pdf_metrics_bundle
        if pdf_bundle is not None and pdf_bundle.pages:
            geometry_tolerance_pt = effective_geometry_tolerance_pt(context)
            measurement = check_body_margins(
                pdf_bundle.spans,
                pdf_bundle.pages,
                geometry_tolerance_pt=geometry_tolerance_pt,
            )
            layout_measurement = check_layout_object_margins(
                extract_pdf_layout_objects(context.pdf_path),
                pdf_bundle.pages,
                geometry_tolerance_pt=geometry_tolerance_pt,
            )
            if measurement.violations:
                pdf_ok = False
                violation = measurement.violations[0]
                pdf_page = violation.span.page
                violation_bbox = violation.span.bbox
                left, right, top, bottom = violation.bounds
                overflow = bbox_margin_overflow(violation_bbox, violation.page)
                delta_pt = max(overflow)
                overflow_text = ",".join(f"{value:.1f}" for value in overflow)
                description = (
                    f"rule_id={rule.id}; path={pdf_path or '<pdf>'}; page={pdf_page}; "
                    f"bbox=[{_bbox_value(violation_bbox)}]; "
                    f"bounds=[{left:.1f},{right:.1f},{top:.1f},{bottom:.1f}]; "
                    f"overflow_pt=[{overflow_text}]; delta_pt={delta_pt:.2f}; "
                    f"geometry_tolerance_pt={geometry_tolerance_pt:.2f}; "
                    "classification=body; "
                    "reason=not_repeated_header_footer_or_page_number"
                )
                pdf_evidence = _metric_evidence(
                    rule.id,
                    path=pdf_path,
                    page=pdf_page,
                    bbox=violation_bbox,
                    description=description,
                )
            elif layout_measurement.violations:
                pdf_ok = False
                layout_violation = layout_measurement.violations[0]
                pdf_page = layout_violation.item.page
                layout_bbox = layout_violation.item.bbox
                left, right, top, bottom = layout_violation.bounds
                overflow = bbox_margin_overflow(layout_bbox, layout_violation.page)
                delta_pt = max(overflow)
                overflow_text = ",".join(f"{value:.1f}" for value in overflow)
                description = (
                    f"rule_id={rule.id}; path={pdf_path or '<pdf>'}; page={pdf_page}; "
                    f"bbox=[{_bbox_value(layout_bbox)}]; "
                    f"bounds=[{left:.1f},{right:.1f},{top:.1f},{bottom:.1f}]; "
                    f"overflow_pt=[{overflow_text}]; delta_pt={delta_pt:.2f}; "
                    f"geometry_tolerance_pt={geometry_tolerance_pt:.2f}; "
                    f"classification={layout_violation.item.kind}; "
                    "reason=not_repeated_header_footer"
                )
                pdf_evidence = _metric_evidence(
                    rule.id,
                    path=pdf_path,
                    page=pdf_page,
                    bbox=layout_bbox,
                    description=description,
                )
            elif measurement.invalid_bbox_count:
                diagnostic_span = _first_span_on_page(pdf_bundle.spans, None)
                pdf_page = (
                    diagnostic_span.page
                    if diagnostic_span is not None
                    else pdf_bundle.pages[0].number
                )
                diagnostic_bbox = diagnostic_span.bbox if diagnostic_span is not None else None
                pdf_missing_message = (
                    "обнаружены spans с ненадёжным bbox; соблюдение полей нельзя подтвердить"
                )
                description = (
                    f"rule_id={rule.id}; path={pdf_path or '<pdf>'}; "
                    f"page={pdf_page or 'unknown'}; "
                    f"bbox=[{_bbox_value(diagnostic_bbox)}]; "
                    f"measured_pages={len(measurement.measured_pages)}; "
                    f"invalid_bbox={measurement.invalid_bbox_count}; "
                    "diagnostic=unreliable_geometry"
                )
                pdf_evidence = _metric_evidence(
                    rule.id,
                    path=pdf_path,
                    page=pdf_page,
                    bbox=diagnostic_bbox,
                    description=description,
                )
            elif measurement.content_spans:
                pdf_ok = True
                body_observation = measurement.max_observed
                layout_observation = layout_measurement.max_observed
                body_delta = (
                    max(
                        bbox_margin_overflow(
                            body_observation.span.bbox,
                            body_observation.page,
                        )
                    )
                    if body_observation is not None
                    else -1.0
                )
                layout_delta = (
                    max(
                        bbox_margin_overflow(
                            layout_observation.item.bbox,
                            layout_observation.page,
                        )
                    )
                    if layout_observation is not None
                    else -1.0
                )
                if layout_observation is not None and layout_delta > body_delta:
                    pdf_page = layout_observation.item.page
                    observed_bbox = layout_observation.item.bbox
                    left, right, top, bottom = layout_observation.bounds
                    delta_pt = layout_delta
                    classification = layout_observation.item.kind
                else:
                    assert body_observation is not None
                    pdf_page = body_observation.span.page
                    observed_bbox = body_observation.span.bbox
                    left, right, top, bottom = body_observation.bounds
                    delta_pt = body_delta
                    classification = "body"
                excluded = (
                    ",".join(
                        f"{kind}:{count}"
                        for kind, count in (
                            *measurement.excluded_counts,
                            *layout_measurement.excluded_counts,
                        )
                    )
                    or "none"
                )
                description = (
                    f"rule_id={rule.id}; path={pdf_path or '<pdf>'}; page={pdf_page}; "
                    f"bbox=[{_bbox_value(observed_bbox)}]; "
                    f"bounds=[{left:.1f},{right:.1f},{top:.1f},{bottom:.1f}]; "
                    f"delta_pt={delta_pt:.2f}; "
                    f"geometry_tolerance_pt={geometry_tolerance_pt:.2f}; "
                    f"classification={classification}; "
                    f"measured_pages={len(measurement.measured_pages)}; "
                    f"content_spans={len(measurement.content_spans)}; "
                    f"classified_marginalia={excluded}"
                )
                pdf_evidence = _metric_evidence(
                    rule.id,
                    path=pdf_path,
                    page=pdf_page,
                    bbox=observed_bbox,
                    description=description,
                )
            else:
                diagnostic_span = _first_span_on_page(pdf_bundle.spans, None)
                pdf_page = (
                    diagnostic_span.page
                    if diagnostic_span is not None
                    else pdf_bundle.pages[0].number
                )
                empty_bbox = diagnostic_span.bbox if diagnostic_span is not None else None
                excluded = (
                    ",".join(
                        f"{kind}:{count}"
                        for kind, count in (
                            *measurement.excluded_counts,
                            *layout_measurement.excluded_counts,
                        )
                    )
                    or "none"
                )
                pdf_missing_message = (
                    "надёжный body region не найден; соблюдение полей нельзя подтвердить"
                )
                description = (
                    f"rule_id={rule.id}; path={pdf_path or '<pdf>'}; "
                    f"page={pdf_page or 'unknown'}; bbox=[{_bbox_value(empty_bbox)}]; "
                    f"content_spans=0; classified_marginalia={excluded}; "
                    f"geometry_tolerance_pt={geometry_tolerance_pt:.2f}; "
                    "diagnostic=no_reliable_body_region"
                )
                pdf_evidence = _metric_evidence(
                    rule.id,
                    path=pdf_path,
                    page=pdf_page,
                    bbox=empty_bbox,
                    description=description,
                )
        return _combine_class_pdf(
            context,
            rule,
            class_ok=class_ok,
            pdf_ok=pdf_ok,
            pass_message=(
                "поля "
                f"{MARGINS_MM['left']}/{MARGINS_MM['right']}/"
                f"{MARGINS_MM['top']}/{MARGINS_MM['bottom']} мм соблюдены"
            ),
            class_fail_message="класс не задаёт geometry с требуемыми полями",
            pdf_fail_message="текст выходит за допустимые поля страницы",
            class_missing_message="защищённый .cls недоступен",
            pdf_missing_message=pdf_missing_message,
            pdf_path=pdf_path,
            pdf_page=pdf_page,
            pdf_evidence=pdf_evidence,
        )


def formatting_rules() -> tuple[
    Fmt01BodyFontRule,
    Fmt02HeadingBoldRule,
    Fmt03LineSpacingRule,
    Fmt04ParindentRule,
    Fmt05MarginsRule,
]:
    return (
        Fmt01BodyFontRule(),
        Fmt02HeadingBoldRule(),
        Fmt03LineSpacingRule(),
        Fmt04ParindentRule(),
        Fmt05MarginsRule(),
    )
