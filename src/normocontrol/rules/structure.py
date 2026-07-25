"""STR-01..04 formal rules."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from normocontrol.domain import Finding, FindingStatus, RuleLayer, Severity
from normocontrol.extract.base import SectionKind
from normocontrol.rubric.models import EffectiveRule, WorkProfile
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader

_FUZZY_THRESHOLD = 0.9

_CANONICAL_SOFTWARE: tuple[str, ...] = (
    "Аннотация",
    "Введение",
    "Обзор НТИ",
    "Структурный системный анализ",
    "Постановка задачи",
    "Архитектурно-техническое решение",
    "Математическая модель",
    "Алгоритм",
    "Программная реализация",
    "Анализ результатов",
    "Заключение",
    "Список источников",
    "Приложения",
)

_SECTION_ALIASES: dict[str, str] = {
    "обзор научно-технической информации": "Обзор НТИ",
    "структурный анализ": "Структурный системный анализ",
    "архитектурное решение": "Архитектурно-техническое решение",
    "программная реализация системы": "Программная реализация",
    "список литературы": "Список источников",
    "библиография": "Список источников",
}

_PAGE_RANGES: dict[str, tuple[int, int]] = {
    "Введение": (2, 3),
    "Обзор НТИ": (3, 5),
    "Структурный системный анализ": (6, 7),
    "Постановка задачи": (2, 3),
    "Архитектурно-техническое решение": (4, 6),
    "Математическая модель": (4, 6),
    "Алгоритм": (4, 5),
    "Программная реализация": (3, 5),
    "Анализ результатов": (2, 4),
    "Заключение": (1, 2),
}


def _normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFC", title).casefold().replace("ё", "е")
    normalized = " ".join(normalized.split())
    return _SECTION_ALIASES.get(normalized, title.strip())


def _fuzzy_match(left: str, right: str) -> bool:
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio() >= _FUZZY_THRESHOLD


def _canonical_sections(profile: WorkProfile) -> tuple[str, ...]:
    del profile
    return _CANONICAL_SOFTWARE


class Str01SectionOrderRule:
    rule_id = "STR-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        observed = [
            section.title
            for section in reader.snapshot.sections
            if section.kind not in {SectionKind.DOCUMENT} and section.level <= 2
        ]
        expected = _canonical_sections(context.rubric.work_profile)
        normalized_observed = [_normalize_title(title) for title in observed]
        index = 0
        for title in normalized_observed:
            if index >= len(expected):
                break
            if _fuzzy_match(title, expected[index]) or title == expected[index]:
                index += 1
        if index < len(expected):
            missing = expected[index]
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.FAIL,
                        message=f"нарушен порядок разделов; ожидался «{missing}»",
                    ),
                )
            )
        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="обязательные разделы найдены в ожидаемом порядке",
                ),
            )
        )


class Str02SubsubsectionRule:
    rule_id = "STR-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        if reader.contains_subsubsection():
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.CLASS,
                        status=FindingStatus.FAIL,
                        message="обнаружена команда \\subsubsection",
                    ),
                )
            )
        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.CLASS,
                    status=FindingStatus.PASS,
                    message="лишняя вложенность подразделов не обнаружена",
                ),
            )
        )


class Str03SubsectionPagesRule:
    rule_id = "STR-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None and (
            context.pdf_path is not None
            or (context.bundle is not None and bool(context.bundle.pages))
        )

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        if context.bundle is None or not context.bundle.pages:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.UNVERIFIABLE,
                        message="PDF с картой страниц недоступен",
                    ),
                )
            )
        assert context.latex is not None
        sections = context.bundle.sections
        findings: list[Finding] = []
        subsections = [
            section
            for section in sections
            if section.level == 3 and section.page_start and section.page_end
        ]
        for section in subsections:
            span = (
                section.page_end - section.page_start
                if section.page_end and section.page_start
                else 0
            )
            if span < 1:
                findings.append(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.WARN,
                        severity=Severity.WARN,
                        message=f"подраздел «{section.title}» короче одной страницы",
                        page=section.page_start,
                    )
                )
        if not findings:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="подразделы занимают не менее одной страницы",
                )
            )
        return RuleRunOutcome(findings=tuple(findings))


class Str04SectionVolumeRule:
    rule_id = "STR-04"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        return Str03SubsectionPagesRule().supports(context, rule)

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        if context.bundle is None:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.UNVERIFIABLE,
                        message="PDF с картой страниц недоступен",
                    ),
                )
            )
        assert context.latex is not None
        findings: list[Finding] = []
        for section in context.bundle.sections:
            canonical = _normalize_title(section.title)
            bounds = _PAGE_RANGES.get(canonical)
            if bounds is None or section.page_start is None or section.page_end is None:
                continue
            pages = section.page_end - section.page_start + 1
            low, high = bounds
            if pages < low or pages > high:
                findings.append(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.WARN,
                        severity=Severity.WARN,
                        message=(
                            f"раздел «{section.title}»: {pages} стр.; рекомендуется {low}–{high}"
                        ),
                        page=section.page_start,
                    )
                )
        if not findings:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="объёмы разделов в рекомендуемых диапазонах",
                )
            )
        return RuleRunOutcome(findings=tuple(findings))


def structure_rules() -> tuple[
    Str01SectionOrderRule,
    Str02SubsubsectionRule,
    Str03SubsectionPagesRule,
    Str04SectionVolumeRule,
]:
    return (
        Str01SectionOrderRule(),
        Str02SubsubsectionRule(),
        Str03SubsectionPagesRule(),
        Str04SectionVolumeRule(),
    )
