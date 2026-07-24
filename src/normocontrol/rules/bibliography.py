"""BIB-01..05 formal bibliography rules."""

from __future__ import annotations

import re
from pathlib import Path

from normocontrol.domain import FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._class_text import class_file_text
from normocontrol.rules._rule_outcomes import combine_class_script, rule_outcome
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.bib_parser import BibEntry, entry_field, load_bib_entries
from normocontrol.rules.cite_symbols import (
    cite_keys,
    contains_footcite,
    footnote_bibliography_warnings,
    manual_bracket_citations,
    nocite_keys,
)
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "article": ("author", "title", "year"),
    "book": ("author", "title", "year"),
    "inproceedings": ("author", "title", "year"),
    "online": ("author", "title", "year", "url"),
    "misc": ("author", "title", "year"),
}
_DEFAULT_REQUIRED = ("author", "title", "year")


def _reader(context: ExecutionContext) -> LatexProjectReader:
    assert context.latex is not None
    return LatexProjectReader.load(context.latex.root, context.latex.main_tex)


def _resolved_bib_paths(context: ExecutionContext) -> tuple[Path, ...]:
    assert context.latex is not None
    return tuple(
        path if path.is_absolute() else context.latex.root / path for path in context.bib_paths
    )


def _bib_entries(context: ExecutionContext) -> tuple[BibEntry, ...]:
    return load_bib_entries(_resolved_bib_paths(context))


def _missing_fields(entry: BibEntry) -> tuple[str, ...]:
    required = _REQUIRED_FIELDS.get(entry.entry_type, _DEFAULT_REQUIRED)
    missing: list[str] = []
    for field in required:
        if not entry_field(entry, field):
            missing.append(field)
    return tuple(missing)


def _class_has_gost_numeric(cls_text: str) -> bool:
    return (
        re.search(r"style\s*=\s*gost-numeric", cls_text, re.IGNORECASE) is not None
        and re.search(r"sorting\s*=\s*none", cls_text, re.IGNORECASE) is not None
        and re.search(r"biblatex-gost|biblatex", cls_text, re.IGNORECASE) is not None
    )


class Bib01IntextReferencesRule:
    rule_id = "BIB-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        reader = _reader(context)
        body = reader.snapshot.body
        if contains_footcite(body):
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.FAIL,
                message="обнаружен запрещённый \\footcite",
            )
        warnings = footnote_bibliography_warnings(body)
        if warnings:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message="; ".join(dict.fromkeys(warnings)),
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="используются только затекстовые ссылки",
        )


class Bib02NumericCitationStyleRule:
    rule_id = "BIB-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        class_ok = cls_text is not None and _class_has_gost_numeric(cls_text)
        reader = _reader(context)
        manual = manual_bracket_citations(reader.snapshot.body)
        script_ok = not manual
        return combine_class_script(
            rule,
            class_ok=class_ok,
            script_ok=script_ok,
            pass_message="числовые ссылки через biblatex-gost без ручных [N]",
            class_fail_message="класс не задаёт biblatex-gost style=gost-numeric, sorting=none",
            script_fail_message=f"ручные ссылки в тексте: {', '.join(manual[:3])}",
            class_missing_message="защищённый .cls недоступен",
            script_missing_message="исходник LaTeX недоступен",
        )


class Bib03GostBibliographyRule:
    rule_id = "BIB-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        cls_text = class_file_text(context)
        class_ok = cls_text is not None and _class_has_gost_numeric(cls_text)
        entries = _bib_entries(context)
        if not entries:
            return combine_class_script(
                rule,
                class_ok=class_ok,
                script_ok=None,
                pass_message="библиографические описания соответствуют ГОСТ",
                class_fail_message="класс не задаёт ГОСТ-совместимый biblatex-gost",
                script_fail_message="неполные .bib записи",
                class_missing_message="защищённый .cls недоступен",
                script_missing_message="файлы .bib не найдены",
            )
        invalid = [
            f"{entry.key}: {', '.join(_missing_fields(entry))}"
            for entry in entries
            if _missing_fields(entry)
        ]
        script_ok = not invalid
        return combine_class_script(
            rule,
            class_ok=class_ok,
            script_ok=script_ok,
            pass_message="библиографические описания соответствуют ГОСТ",
            class_fail_message="класс не задаёт ГОСТ-совместимый biblatex-gost",
            script_fail_message=f"неполные .bib записи: {'; '.join(invalid[:5])}",
            class_missing_message="защищённый .cls недоступен",
            script_missing_message="файлы .bib не найдены",
        )


class Bib04OnlineUrldateRule:
    rule_id = "BIB-04"
    required_sources = frozenset({SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return bool(context.bib_paths)

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        missing: list[str] = []
        for entry in _bib_entries(context):
            url = entry_field(entry, "url")
            if url and not entry_field(entry, "urldate"):
                missing.append(entry.key)
        if missing:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.FAIL,
                message=f"нет urldate у записей: {', '.join(missing[:5])}",
            )
        if not _bib_entries(context):
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message="записи .bib не обнаружены",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="у электронных ресурсов указана дата обращения",
        )


class Bib05UncitedBibliographyRule:
    rule_id = "BIB-05"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        reader = _reader(context)
        body = reader.snapshot.body
        nocite = nocite_keys(body)
        if "*" in nocite:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message="обнаружен \\nocite{*}",
            )
        cited = cite_keys(body)
        extra_nocite = sorted(key for key in nocite if key not in cited)
        if extra_nocite:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message=f"\\nocite без \\cite: {', '.join(extra_nocite[:5])}",
            )
        all_keys = {entry.key for entry in _bib_entries(context)}
        uncited = sorted(all_keys - cited)
        if uncited:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message=f"источники без ссылок в тексте: {', '.join(uncited[:5])}",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="все источники процитированы в тексте",
        )


def bibliography_rules() -> tuple[
    Bib01IntextReferencesRule,
    Bib02NumericCitationStyleRule,
    Bib03GostBibliographyRule,
    Bib04OnlineUrldateRule,
    Bib05UncitedBibliographyRule,
]:
    return (
        Bib01IntextReferencesRule(),
        Bib02NumericCitationStyleRule(),
        Bib03GostBibliographyRule(),
        Bib04OnlineUrldateRule(),
        Bib05UncitedBibliographyRule(),
    )
