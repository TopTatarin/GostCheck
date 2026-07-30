"""TSK-02 deterministic task-list item length check."""

from __future__ import annotations

import re
import unicodedata

from pylatexenc.latex2text import LatexNodes2Text  # type: ignore[import-untyped]

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.extract.base import Section
from normocontrol.extract.latex import _protect_literal_environments, _strip_comments
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader

_TASK_TITLES = frozenset(
    {
        "постановка задачи",
        "постановка задач",
        "цель и задачи",
        "задачи исследования",
    }
)
_LIST_RE = re.compile(
    r"\\begin\s*\{(?P<environment>itemize|enumerate)\}"
    r"(?P<body>.*?)"
    r"\\end\s*\{(?P=environment)\}",
    re.DOTALL | re.IGNORECASE,
)
_ITEM_RE = re.compile(r"\\item(?:\s*\[[^\]]*\])?", re.IGNORECASE)
_MIN_TASK_ITEM_CHARS = 30


def _normalized_title(title: str) -> str:
    value = unicodedata.normalize("NFC", title).casefold().replace("ё", "е")
    value = re.sub(r"^\s*\d+(?:\.\d+)*[.\s:—-]+", "", value)
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def _task_section(sections: tuple[Section, ...]) -> Section | None:
    return next(
        (
            section
            for section in sections
            if section.level <= 2 and _normalized_title(section.title) in _TASK_TITLES
        ),
        None,
    )


def _structural_source(text: str) -> str:
    opaque, _protected = _protect_literal_environments(text)
    return _strip_comments(opaque)


def _plain_length(source: str) -> int:
    plain = LatexNodes2Text().latex_to_text(source)
    normalized = " ".join(unicodedata.normalize("NFC", plain).split())
    return len(normalized)


def _task_item_lengths(body: str) -> tuple[int, ...]:
    prepared = _structural_source(body)
    lengths: list[int] = []
    for list_match in _LIST_RE.finditer(prepared):
        list_body = list_match.group("body")
        items = tuple(_ITEM_RE.finditer(list_body))
        for index, item in enumerate(items):
            start = item.end()
            end = items[index + 1].start() if index + 1 < len(items) else len(list_body)
            lengths.append(_plain_length(list_body[start:end]))
    return tuple(lengths)


class Tsk02TaskItemLengthRule:
    rule_id = "TSK-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        section = _task_section(reader.snapshot.sections)
        if section is None:
            return self._finding(
                rule,
                status=FindingStatus.UNVERIFIABLE,
                message="раздел «Постановка задачи» не найден",
            )
        body = reader.section_body(section.title)
        if body is None:
            return self._finding(
                rule,
                status=FindingStatus.UNVERIFIABLE,
                message="текст раздела «Постановка задачи» недоступен",
                section=section,
            )
        lengths = _task_item_lengths(body)
        if not lengths:
            return self._finding(
                rule,
                status=FindingStatus.UNVERIFIABLE,
                message="в разделе постановки задачи проверяемый список задач не найден",
                section=section,
            )
        short = tuple(length for length in lengths if length < _MIN_TASK_ITEM_CHARS)
        if short:
            return self._finding(
                rule,
                status=FindingStatus.WARN,
                message=(
                    f"коротких пунктов задач: {len(short)}; минимальная длина {min(short)} символов"
                ),
                section=section,
            )
        return self._finding(
            rule,
            status=FindingStatus.PASS,
            message="все пункты списка задач содержат не менее 30 символов",
            section=section,
        )

    @staticmethod
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


def task_item_rules() -> tuple[Tsk02TaskItemLengthRule]:
    return (Tsk02TaskItemLengthRule(),)
