"""ANN-03 declared-versus-actual document count checks."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.extract.base import Section, SectionKind
from normocontrol.extract.latex import _protect_literal_environments, _strip_comments
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader

_COUNT_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "pages": re.compile(r"(?<!\d)(\d{1,5})\s*(?:страниц(?:а|ы)?|стр\.?)\b", re.IGNORECASE),
    "figures": re.compile(r"(?<!\d)(\d{1,5})\s*рисун(?:ок|ка|ки|ков)\b", re.IGNORECASE),
    "tables": re.compile(r"(?<!\d)(\d{1,5})\s*таблиц(?:а|ы|у)?\b", re.IGNORECASE),
    "appendices": re.compile(
        r"(?<!\d)(\d{1,5})\s*приложени(?:е|я|й)\b",
        re.IGNORECASE,
    ),
}
_FLOAT_BEGIN_RE = re.compile(
    r"\\begin\s*\{(?P<environment>figure\*?|table\*?|longtable\*?)\}",
    re.IGNORECASE,
)
_APPENDIX_MARKER_RE = re.compile(
    r"\\appendix\b|\\begin\s*\{appendices\}",
    re.IGNORECASE,
)
_TOP_LEVEL_HEADING_RE = re.compile(
    r"\\(?:chapter|section)\*?\s*\{(?P<title>[^{}]+)\}",
    re.IGNORECASE,
)
_EXPLICIT_APPENDIX_RE = re.compile(
    r"^(?:приложение|appendix)\s+[a-zа-яё0-9](?:\b|[.\s:—-])",
    re.IGNORECASE,
)
_METRIC_LABELS = {
    "pages": "страниц",
    "figures": "рисунков",
    "tables": "таблиц",
    "appendices": "приложений",
}


def _structural_source(text: str) -> str:
    opaque, _protected = _protect_literal_environments(text)
    return _strip_comments(opaque)


def _declared_counts(annotation: str) -> tuple[dict[str, int] | None, str | None]:
    prepared = _structural_source(annotation)
    declared: dict[str, int] = {}
    for metric, pattern in _COUNT_PATTERNS.items():
        values = {int(match.group(1)) for match in pattern.finditer(prepared)}
        if len(values) > 1:
            return None, "аннотация содержит противоречивые заявленные количества"
        if values:
            declared[metric] = values.pop()
    if set(declared) != set(_COUNT_PATTERNS):
        return None, "в аннотации не найдены все четыре заявленных количества"
    return declared, None


def _actual_source_counts(body: str) -> dict[str, int]:
    prepared = _structural_source(body)
    environments = [
        match.group("environment").casefold() for match in _FLOAT_BEGIN_RE.finditer(prepared)
    ]
    marker = _APPENDIX_MARKER_RE.search(prepared)
    appendix_region = prepared[marker.end() :] if marker is not None else prepared
    appendix_count = 0
    for match in _TOP_LEVEL_HEADING_RE.finditer(appendix_region):
        title = unicodedata.normalize("NFC", match.group("title")).strip()
        if marker is not None or _EXPLICIT_APPENDIX_RE.match(title) is not None:
            appendix_count += 1
    return {
        "figures": sum(environment.startswith("figure") for environment in environments),
        "tables": sum(
            environment.startswith(("table", "longtable")) for environment in environments
        ),
        "appendices": appendix_count,
    }


def _annotation_section(sections: tuple[Section, ...]) -> Section | None:
    return next(
        (
            section
            for section in sections
            if section.kind is SectionKind.ANNOTATION
            or unicodedata.normalize("NFC", section.title).casefold() in {"аннотация", "реферат"}
        ),
        None,
    )


class Ann03DeclaredCountsRule:
    """Compare all four annotation declarations with compiled/source facts."""

    rule_id = "ANN-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.PDF})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        annotation = _annotation_section(reader.snapshot.sections)
        if annotation is None:
            return self._unverifiable(rule, "раздел «Аннотация» не найден")
        body = reader.section_body(annotation.title)
        if body is None:
            return self._unverifiable(rule, "текст раздела «Аннотация» недоступен")

        declared, declaration_error = _declared_counts(body)
        if declared is None:
            assert declaration_error is not None
            return self._unverifiable(
                rule,
                declaration_error,
                evidence_locator=annotation.locator,
            )

        pdf_bundle = context.pdf_metrics_bundle
        if pdf_bundle is None or not pdf_bundle.pages:
            return self._unverifiable(rule, "счётчик страниц PDF недоступен")
        page_numbers = tuple(page.number for page in pdf_bundle.pages)
        if page_numbers != tuple(range(1, len(page_numbers) + 1)):
            return self._unverifiable(rule, "нумерация метрик страниц PDF ненадёжна")

        actual = {
            "pages": len(pdf_bundle.pages),
            **_actual_source_counts(reader.snapshot.body),
        }
        mismatches = [
            f"{_METRIC_LABELS[metric]}: заявлено {declared[metric]}, факт {actual[metric]}"
            for metric in _COUNT_PATTERNS
            if declared[metric] != actual[metric]
        ]
        if mismatches:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.FAIL,
                        message="; ".join(mismatches),
                        evidence_locator=annotation.locator,
                    ),
                )
            )

        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="заявленные количества совпадают с фактическими счётчиками",
                    evidence_locator=annotation.locator,
                ),
            )
        )

    @staticmethod
    def _unverifiable(
        rule: EffectiveRule,
        message: str,
        *,
        evidence_locator: str | None = None,
    ) -> RuleRunOutcome:
        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.UNVERIFIABLE,
                    message=message,
                    evidence_locator=evidence_locator,
                ),
            )
        )


def annotation_rules() -> tuple[Ann03DeclaredCountsRule]:
    return (Ann03DeclaredCountsRule(),)
