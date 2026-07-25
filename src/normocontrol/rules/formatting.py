"""FMT-01..05 PDF formatting and class-file rules."""

from __future__ import annotations

import re

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._class_text import class_file_text
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules._pdf_metrics import (
    MARGINS_MM,
    bbox_within_margins,
    body_spans,
    font_size_match_ratio,
    heading_spans,
    median_line_spacing_ratio,
    page_text_bbox,
    span_is_bold,
    times_new_roman_ratio,
)
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind

_FONT_SIZE_TOLERANCE_PT = 0.5
_BODY_FONT_RATIO_MIN = 0.95
_LINE_SPACING_TARGET = 1.5
_LINE_SPACING_TOLERANCE = 0.10


def effective_font_size_pt(context: ExecutionContext) -> float:
    """Resolve approved font size from config with rubric defaults."""
    override = context.config.params.font_size_pt
    default = context.rubric.meta.params_to_approve.font_size_pt
    return float(override if override is not None else default)


def pdf_metrics_available(context: ExecutionContext) -> bool:
    """Return whether a PDF bundle exposes a usable text layer."""
    return context.has_pdf_text_layer


def _pass(rule: EffectiveRule, message: str) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.PASS,
                message=message,
            ),
        )
    )


def _fail(rule: EffectiveRule, message: str, *, page: int | None = None) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.FAIL,
                message=message,
                page=page,
            ),
        )
    )


def _unverifiable(rule: EffectiveRule, message: str) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.UNVERIFIABLE,
                message=message,
            ),
        )
    )


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
) -> RuleRunOutcome:
    class_required = context.latex is not None
    pdf_required = context.pdf_only
    if class_required and class_ok is False:
        return _fail(rule, class_fail_message)
    if pdf_ok is False:
        return _fail(rule, pdf_fail_message)
    if class_required and class_ok is None:
        return _unverifiable(rule, class_missing_message)
    if pdf_required and pdf_ok is None:
        return _unverifiable(rule, pdf_missing_message)
    return _pass(rule, pass_message)


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
        if pdf_metrics_available(context):
            pdf_bundle = context.pdf_metrics_bundle
            assert pdf_bundle is not None
            spans = body_spans(pdf_bundle.spans)
            if spans:
                expected = effective_font_size_pt(context)
                tnr_ratio = times_new_roman_ratio(spans)
                size_ratio = font_size_match_ratio(
                    spans,
                    expected_pt=expected,
                    tolerance_pt=_FONT_SIZE_TOLERANCE_PT,
                )
                pdf_ok = tnr_ratio >= _BODY_FONT_RATIO_MIN and size_ratio >= _BODY_FONT_RATIO_MIN
        return _combine_class_pdf(
            context,
            rule,
            class_ok=class_ok,
            pdf_ok=pdf_ok,
            pass_message="основной текст соответствует Times New Roman и кеглю",
            class_fail_message="класс не задаёт Times New Roman через fontspec",
            pdf_fail_message="менее 95% PDF-спанов соответствуют Times New Roman/кеглю",
            class_missing_message="защищённый .cls недоступен",
            pdf_missing_message="PDF text layer недоступен для проверки шрифта",
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
        pdf_bundle = context.pdf_metrics_bundle
        if pdf_metrics_available(context) and pdf_bundle is not None and pdf_bundle.pages:
            violations: list[int] = []
            measured_pages = 0
            measurable_spans = body_spans(pdf_bundle.spans)
            for page in pdf_bundle.pages:
                bbox = page_text_bbox(measurable_spans, page.number)
                if bbox is None:
                    continue
                measured_pages += 1
                metric_page = page
                if page.rotation in {90, 270}:
                    metric_page = page.model_copy(
                        update={
                            "width": page.height,
                            "height": page.width,
                            "rotation": 0,
                        }
                    )
                if not bbox_within_margins(bbox, metric_page):
                    violations.append(page.number)
            if measured_pages:
                pdf_ok = not violations
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
            pdf_missing_message="PDF text layer недоступен для проверки полей",
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
