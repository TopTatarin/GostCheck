"""FIG-01..07 formal rules."""

from __future__ import annotations

import re

from normocontrol.domain import FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._class_text import class_file_text
from normocontrol.rules._rule_outcomes import combine_class_script, rule_outcome
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.formatting import pdf_metrics_available
from normocontrol.rules.latex_source import LatexProjectReader
from normocontrol.rules.latex_symbols import (
    contains_abbreviated_figure_reference,
    figure_blocks,
    figure_number_from_caption,
    reference_targets,
)

_FIGURE_REF_PAGE_RE = re.compile(
    r"(?:рисун(?:ок|ке|ка)|figure)\s+(\d+)",
    re.IGNORECASE,
)


def _pdf_span_text(text: str) -> str:
    """Normalize PDF text spans for caption matching."""
    return text.replace("\xa0", " ")


def _reader(context: ExecutionContext) -> LatexProjectReader:
    assert context.latex is not None
    return LatexProjectReader.load(context.latex.root, context.latex.main_tex)


class Fig01PlacementRule:
    rule_id = "FIG-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None and pdf_metrics_available(context)

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.bundle is not None
        reader = _reader(context)
        warnings: list[str] = []
        for block in figure_blocks(reader.snapshot.body):
            number = figure_number_from_caption(block.caption)
            if number is None or block.label is None:
                continue
            caption_pages = [
                span.page
                for span in context.bundle.spans
                if f"Рисунок {number}" in _pdf_span_text(span.text)
                or f"рисунок {number}" in _pdf_span_text(span.text).casefold()
            ]
            if not caption_pages:
                continue
            caption_page = min(caption_pages)
            ref_pages: list[int] = []
            for span in context.bundle.spans:
                match = _FIGURE_REF_PAGE_RE.search(span.text)
                if (
                    match
                    and int(match.group(1)) == number
                    and span.page <= caption_page
                ):
                    ref_pages.append(span.page)
            if not ref_pages:
                continue
            first_ref_page = min(ref_pages)
            if caption_page > first_ref_page + 1:
                warnings.append(f"рисунок {number}: подпись на стр. {caption_page}")
        if warnings:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message="; ".join(warnings),
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="размещение подписей рисунков в допустимом диапазоне",
        )


class Fig02FigureReferenceRule:
    rule_id = "FIG-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        reader = _reader(context)
        refs = set(reference_targets(reader.snapshot.body))
        missing: list[str] = []
        for block in figure_blocks(reader.snapshot.body):
            if block.label is None:
                missing.append("figure без \\label")
                continue
            if block.label not in refs:
                missing.append(block.label)
        if missing:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.FAIL,
                message=f"нет ссылок на: {', '.join(missing)}",
            )
        if not figure_blocks(reader.snapshot.body):
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message="рисунки не обнаружены",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="на каждый рисунок есть \\label и \\ref",
        )


class Fig03FigureReferenceStyleRule:
    rule_id = "FIG-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        reader = _reader(context)
        class_ok = cls_text is not None and re.search(
            r"\\(?:newcommand|NewDocumentCommand)\{\\risref\}",
            cls_text,
        ) is not None
        script_ok = not contains_abbreviated_figure_reference(reader.snapshot.body)
        return combine_class_script(
            rule,
            class_ok=class_ok,
            script_ok=script_ok,
            pass_message="ссылки на рисунки оформлены через \\risref",
            class_fail_message="класс не определяет макрос \\risref",
            script_fail_message="обнаружена сокращённая ссылка «рис. N»",
            class_missing_message="защищённый .cls недоступен",
            script_missing_message="исходник LaTeX недоступен",
        )


class Fig04FigureNumberingRule:
    rule_id = "FIG-04"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        if cls_text is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.UNVERIFIABLE,
                message="защищённый .cls недоступен",
            )
        if re.search(r"\\counterwithin\{figure\}|\\numberwithin\{figure\}", cls_text):
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.PASS,
                message="нумерация рисунков настроена в классе",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.CLASS,
            status=FindingStatus.FAIL,
            message="класс не задаёт counterwithin/numberwithin для figure",
        )


class Fig05FigureCaptionFormatRule:
    rule_id = "FIG-05"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        if cls_text is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.UNVERIFIABLE,
                message="защищённый .cls недоступен",
            )
        figure_setup = re.search(
            r"\\captionsetup\s*\[\s*figure\s*\]\{([^}]+)\}",
            cls_text,
            re.IGNORECASE | re.DOTALL,
        )
        if figure_setup is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.FAIL,
                message="нет \\captionsetup[figure]",
            )
        options = figure_setup.group(1).casefold()
        required = ("position=below", "justification=centering", "labelsep=endash")
        if all(item in options.replace(" ", "") for item in required):
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.PASS,
                message="подпись рисунка центрирована под рисунком",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.CLASS,
            status=FindingStatus.FAIL,
            message="captionsetup[figure] не задаёт position/justification/labelsep",
        )


class Fig06CaptionHyphenationRule:
    rule_id = "FIG-06"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        if cls_text is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.UNVERIFIABLE,
                message="защищённый .cls недоступен",
            )
        if re.search(r"hyphenpenalty\s*=\s*10000", cls_text, re.IGNORECASE):
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.PASS,
                message="переносы в подписи рисунка отключены",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.CLASS,
            status=FindingStatus.FAIL,
            message="класс не задаёт hyphenpenalty=10000 для caption",
        )


class Fig07CaptionStretchRule:
    rule_id = "FIG-07"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        if cls_text is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.UNVERIFIABLE,
                message="защищённый .cls недоступен",
            )
        if re.search(r"font\s*=\s*\{\s*stretch\s*=\s*1\s*\}", cls_text, re.IGNORECASE):
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.PASS,
                message="многострочная подпись использует stretch=1",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.CLASS,
            status=FindingStatus.FAIL,
            message="класс не задаёт font={stretch=1} для caption",
        )


def figures_rules() -> tuple[
    Fig01PlacementRule,
    Fig02FigureReferenceRule,
    Fig03FigureReferenceStyleRule,
    Fig04FigureNumberingRule,
    Fig05FigureCaptionFormatRule,
    Fig06CaptionHyphenationRule,
    Fig07CaptionStretchRule,
]:
    return (
        Fig01PlacementRule(),
        Fig02FigureReferenceRule(),
        Fig03FigureReferenceStyleRule(),
        Fig04FigureNumberingRule(),
        Fig05FigureCaptionFormatRule(),
        Fig06CaptionHyphenationRule(),
        Fig07CaptionStretchRule(),
    )
