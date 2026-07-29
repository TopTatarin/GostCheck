"""Formal structure checks for ALG-01 and ALG-03."""

from __future__ import annotations

import re
import unicodedata

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.extract.base import Section
from normocontrol.extract.latex import _protect_literal_environments, _strip_comments
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader

_ALGORITHM_TITLE_RE = re.compile(
    r"^(?:алгоритм(?:\b|\s)|(?:описание|разработка|проектирование)\s+алгоритм(?:а|ов)?\b)",
    re.IGNORECASE,
)
_REPRESENTATION_RE = re.compile(
    r"\\begin\s*\{(?:figure\*?|algorithm|algorithmic|algorithm2e)\}",
    re.IGNORECASE,
)
_BLOCK_DESCRIPTION_RE = re.compile(r"(?<!\w)блок\s+\d+\s*\.", re.IGNORECASE)


def _normalized_title(title: str) -> str:
    value = unicodedata.normalize("NFC", title).casefold().replace("ё", "е")
    value = re.sub(r"^\s*\d+(?:\.\d+)*[.\s:—-]+", "", value)
    return " ".join(value.split())


def _algorithm_section(sections: tuple[Section, ...]) -> Section | None:
    return next(
        (
            section
            for section in sections
            if section.level <= 2
            and _ALGORITHM_TITLE_RE.match(_normalized_title(section.title)) is not None
        ),
        None,
    )


def _structural_source(text: str) -> str:
    opaque, _protected = _protect_literal_environments(text)
    return unicodedata.normalize("NFC", _strip_comments(opaque))


def _algorithm_body(
    context: ExecutionContext,
) -> tuple[Section | None, str | None]:
    assert context.latex is not None
    reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
    section = _algorithm_section(reader.snapshot.sections)
    if section is None:
        return None, None
    return section, reader.section_body(section.title)


def _finding(
    rule: EffectiveRule,
    *,
    status: FindingStatus,
    message: str,
    section: Section | None = None,
) -> RuleRunOutcome:
    return RuleRunOutcome(
        findings=(
            make_rule_finding(
                rule,
                layer=RuleLayer.SCRIPT,
                status=status,
                message=message,
                evidence_locator=section.locator if section is not None else None,
            ),
        )
    )


class Alg01RepresentationRule:
    rule_id = "ALG-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        section, body = _algorithm_body(context)
        if section is None or body is None:
            return _finding(
                rule,
                status=FindingStatus.UNVERIFIABLE,
                message="раздел «Алгоритм» не найден",
            )
        if _REPRESENTATION_RE.search(_structural_source(body)) is None:
            return _finding(
                rule,
                status=FindingStatus.WARN,
                message="в разделе алгоритма не найдено figure/algorithm-окружение",
                section=section,
            )
        return _finding(
            rule,
            status=FindingStatus.PASS,
            message="в разделе алгоритма найдено структурное представление",
            section=section,
        )


class Alg03BlockDescriptionRule:
    rule_id = "ALG-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        section, body = _algorithm_body(context)
        if section is None or body is None:
            return _finding(
                rule,
                status=FindingStatus.UNVERIFIABLE,
                message="раздел «Алгоритм» не найден",
            )
        if _BLOCK_DESCRIPTION_RE.search(_structural_source(body)) is None:
            return _finding(
                rule,
                status=FindingStatus.WARN,
                message="в разделе алгоритма не найдено описание вида «Блок N.»",
                section=section,
            )
        return _finding(
            rule,
            status=FindingStatus.PASS,
            message="в разделе алгоритма найдено нумерованное описание блоков",
            section=section,
        )


def algorithm_rules() -> tuple[Alg01RepresentationRule, Alg03BlockDescriptionRule]:
    return Alg01RepresentationRule(), Alg03BlockDescriptionRule()
