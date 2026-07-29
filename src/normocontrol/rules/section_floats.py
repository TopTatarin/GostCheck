"""Section-scoped float presence checks for SSA-01, ARC-01, and RES-01."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.extract.base import Section
from normocontrol.extract.latex import _protect_literal_environments, _strip_comments
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader

_ENVIRONMENT_RE = re.compile(
    r"\\begin\s*\{(?P<environment>figure\*?|table\*?|longtable\*?)\}",
    re.IGNORECASE,
)
_SSA_TITLES = frozenset(
    {
        "структурный системный анализ",
        "системный анализ",
        "модель as is",
        "анализ текущего состояния",
    }
)
_ARC_TITLES = frozenset(
    {
        "архитектурно техническое решение",
        "архитектурное решение",
        "архитектура",
        "модель to be",
    }
)
_RES_TITLES = frozenset(
    {
        "анализ результатов",
        "результаты",
        "экспериментальные результаты",
        "оценка результатов",
    }
)


def _normalized_title(title: str) -> str:
    value = unicodedata.normalize("NFC", title).casefold().replace("ё", "е")
    value = re.sub(r"^\s*\d+(?:\.\d+)*[.\s:—-]+", "", value)
    return " ".join(re.findall(r"[\w]+|as is|to be", value, flags=re.UNICODE))


def _matching_sections(
    sections: tuple[Section, ...],
    titles: Collection[str],
) -> tuple[Section, ...]:
    return tuple(
        section
        for section in sections
        if section.level <= 2 and _normalized_title(section.title) in titles
    )


def _structural_source(text: str) -> str:
    opaque, _protected = _protect_literal_environments(text)
    return _strip_comments(opaque)


def _environment_names(body: str) -> frozenset[str]:
    return frozenset(
        match.group("environment").casefold()
        for match in _ENVIRONMENT_RE.finditer(_structural_source(body))
    )


def _run_presence(
    context: ExecutionContext,
    rule: EffectiveRule,
    *,
    titles: Collection[str],
    allowed_environments: Collection[str],
    section_label: str,
    object_label: str,
) -> RuleRunOutcome:
    assert context.latex is not None
    reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
    sections = _matching_sections(reader.snapshot.sections, titles)
    if not sections:
        return _finding(
            rule,
            status=FindingStatus.UNVERIFIABLE,
            message=f"раздел «{section_label}» не найден",
        )

    available: list[Section] = []
    for section in sections:
        body = reader.section_body(section.title)
        if body is None:
            continue
        available.append(section)
        if _environment_names(body) & set(allowed_environments):
            return _finding(
                rule,
                status=FindingStatus.PASS,
                message=f"в разделе «{section_label}» найден {object_label}",
                section=section,
            )

    if not available:
        return _finding(
            rule,
            status=FindingStatus.UNVERIFIABLE,
            message=f"текст раздела «{section_label}» недоступен",
            section=sections[0],
        )
    return _finding(
        rule,
        status=FindingStatus.WARN,
        message=f"в разделе «{section_label}» не найден {object_label}",
        section=available[0],
    )


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


class Ssa01FigurePresenceRule:
    rule_id = "SSA-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        return _run_presence(
            context,
            rule,
            titles=_SSA_TITLES,
            allowed_environments={"figure", "figure*"},
            section_label="Структурный системный анализ",
            object_label="рисунок модели as is",
        )


class Arc01FigurePresenceRule:
    rule_id = "ARC-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        return _run_presence(
            context,
            rule,
            titles=_ARC_TITLES,
            allowed_environments={"figure", "figure*"},
            section_label="Архитектурно-техническое решение",
            object_label="рисунок модели to be",
        )


class Res01FloatPresenceRule:
    rule_id = "RES-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        return _run_presence(
            context,
            rule,
            titles=_RES_TITLES,
            allowed_environments={
                "figure",
                "figure*",
                "table",
                "table*",
                "longtable",
                "longtable*",
            },
            section_label="Анализ результатов",
            object_label="рисунок или таблица итоговых метрик",
        )


def section_float_rules() -> tuple[
    Ssa01FigurePresenceRule,
    Arc01FigurePresenceRule,
    Res01FloatPresenceRule,
]:
    return Ssa01FigurePresenceRule(), Arc01FigurePresenceRule(), Res01FloatPresenceRule()
