"""TAB-01..03 formal rules."""

from __future__ import annotations

import re

from normocontrol.domain import FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._class_text import class_file_text
from normocontrol.rules._rule_outcomes import combine_class_script, rule_outcome
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader
from normocontrol.rules.latex_symbols import (
    longtable_without_continuation_header,
    reference_targets,
    table_blocks,
)


def _reader(context: ExecutionContext) -> LatexProjectReader:
    assert context.latex is not None
    return LatexProjectReader.load(context.latex.root, context.latex.main_tex)


class Tab01TableCaptionFormatRule:
    rule_id = "TAB-01"
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
        table_setup = re.search(
            r"\\captionsetup\s*\[\s*table\s*\]\{([^}]+)\}",
            cls_text,
            re.IGNORECASE | re.DOTALL,
        )
        if table_setup is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.FAIL,
                message="нет \\captionsetup[table]",
            )
        options = table_setup.group(1).casefold().replace(" ", "")
        required = ("position=top", "singlelinecheck=off", "justification=raggedright")
        if all(item in options for item in required):
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS,
                status=FindingStatus.PASS,
                message="подпись таблицы расположена над таблицей слева",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.CLASS,
            status=FindingStatus.FAIL,
            message="captionsetup[table] не задаёт position/singlelinecheck/justification",
        )


class Tab02LongtableContinuationRule:
    rule_id = "TAB-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        reader = _reader(context)
        class_ok = cls_text is not None and (
            re.search(
                r"\\(?:newcommand|NewDocumentCommand)\{\\vkrlongtable\}",
                cls_text,
            )
            is not None
            or re.search(r"\\end(?:first)?head\b", cls_text) is not None
        )
        script_ok = not longtable_without_continuation_header(reader.snapshot.body)
        return combine_class_script(
            rule,
            class_ok=class_ok,
            script_ok=script_ok,
            pass_message="продолжение longtable настроено",
            class_fail_message="класс не задаёт vkrlongtable/endhead",
            script_fail_message="longtable без \\endhead/\\endfirsthead",
            class_missing_message="защищённый .cls недоступен",
            script_missing_message="исходник LaTeX недоступен",
            script_warn=True,
        )


class Tab03TableReferenceRule:
    rule_id = "TAB-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        reader = _reader(context)
        refs = set(reference_targets(reader.snapshot.body))
        missing: list[str] = []
        for block in table_blocks(reader.snapshot.body):
            if block.label is None:
                missing.append("table без \\label")
                continue
            if block.label not in refs:
                missing.append(block.label)
        if missing:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message=f"нет ссылок на: {', '.join(missing)}",
            )
        if not table_blocks(reader.snapshot.body):
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message="таблицы не обнаружены",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="на каждую таблицу есть \\label и \\ref",
        )


def tables_rules() -> tuple[
    Tab01TableCaptionFormatRule,
    Tab02LongtableContinuationRule,
    Tab03TableReferenceRule,
]:
    return (
        Tab01TableCaptionFormatRule(),
        Tab02LongtableContinuationRule(),
        Tab03TableReferenceRule(),
    )
