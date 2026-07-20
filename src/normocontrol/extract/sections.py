"""Deterministic semantic section detection for extracted documents."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import ClassVar

from normocontrol.extract.base import (
    ExtractedDocument,
    HeadingCandidate,
    Section,
    SectionKind,
    make_locator,
)

_ALIASES: dict[SectionKind, tuple[str, ...]] = {
    SectionKind.ANNOTATION: ("аннотация", "реферат", "abstract"),
    SectionKind.INTRODUCTION: ("введение", "introduction"),
    SectionKind.CONCLUSION: (
        "заключение",
        "выводы",
        "выводы и рекомендации",
        "conclusion",
    ),
}
_APPENDIX_RE = re.compile(r"^(?:приложение|appendix)\s+([a-zа-яё0-9])(?:\b|$)", re.IGNORECASE)


def _normalized_title(title: str) -> str:
    normalized = unicodedata.normalize("NFC", title).casefold().replace("ё", "е")
    normalized = re.sub(r"^\s*(?:глава|раздел)\s+\d+[.\s:—-]*", "", normalized)
    normalized = re.sub(r"^\s*\d+(?:\.\d+)*[.\s:—-]+", "", normalized)
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def _semantic_kind(title: str) -> SectionKind:
    normalized = _normalized_title(title)
    if _APPENDIX_RE.match(normalized):
        return SectionKind.APPENDIX
    for kind, aliases in _ALIASES.items():
        for alias in aliases:
            # Fuzzy matching affects addressability only; it never produces a finding or gate.
            if normalized == alias or SequenceMatcher(None, normalized, alias).ratio() >= 0.88:
                return kind
    return SectionKind.OTHER


def _slug(title: str) -> str:
    normalized = _normalized_title(title)
    value = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-")
    return value[:48] or "section"


def _page_range(
    document: ExtractedDocument,
    start: int,
    end: int,
    heading_page: int | None,
) -> tuple[int | None, int | None]:
    pages = sorted(
        {span.page for span in document.spans if span.char_end > start and span.char_start < end}
    )
    if pages:
        return pages[0], pages[-1]
    return heading_page, heading_page


class SectionDetector:
    """Build sections from prioritized AST/outline/typographic heading candidates."""

    _ORIGIN_PRIORITY: ClassVar[dict[str, int]] = {
        "latex_ast": 0,
        "pdf_outline": 1,
        "pdf_heading": 2,
    }

    def detect(self, document: ExtractedDocument) -> tuple[Section, ...]:
        """Return non-overlapping sections covering the entire normalized text."""
        headings = self._deduplicate(document.headings, len(document.text))
        if not headings:
            page_start = document.pages[0].number if document.pages else None
            page_end = document.pages[-1].number if document.pages else None
            return (
                Section(
                    section_id=SectionKind.DOCUMENT.value,
                    title="Документ",
                    kind=SectionKind.DOCUMENT,
                    level=0,
                    char_start=0,
                    char_end=len(document.text),
                    page_start=page_start,
                    page_end=page_end,
                    locator=make_locator(document.source_hash, 0, len(document.text)),
                ),
            )

        result: list[Section] = []
        used_ids: dict[str, int] = {}
        if headings[0].char_start > 0:
            start, end = 0, headings[0].char_start
            page_start, page_end = _page_range(document, start, end, None)
            result.append(
                Section(
                    section_id="document-preamble",
                    title="Преамбула",
                    kind=SectionKind.DOCUMENT,
                    level=0,
                    char_start=start,
                    char_end=end,
                    page_start=page_start,
                    page_end=page_end,
                    locator=make_locator(document.source_hash, start, end),
                )
            )

        for index, heading in enumerate(headings):
            start = heading.char_start
            end = (
                headings[index + 1].char_start if index + 1 < len(headings) else len(document.text)
            )
            kind = _semantic_kind(heading.title)
            base_id = kind.value if kind is not SectionKind.OTHER else _slug(heading.title)
            if kind is SectionKind.APPENDIX:
                match = _APPENDIX_RE.match(_normalized_title(heading.title))
                if match is not None:
                    base_id = f"appendix-{match.group(1)}"
            serial = used_ids.get(base_id, 0) + 1
            used_ids[base_id] = serial
            section_id = base_id if serial == 1 else f"{base_id}-{serial}"
            page_start, page_end = _page_range(document, start, end, heading.page)
            result.append(
                Section(
                    section_id=section_id,
                    title=heading.title,
                    kind=kind,
                    level=heading.level,
                    char_start=start,
                    char_end=end,
                    page_start=page_start,
                    page_end=page_end,
                    locator=make_locator(document.source_hash, start, end),
                )
            )
        return tuple(result)

    def _deduplicate(
        self,
        headings: tuple[HeadingCandidate, ...],
        text_length: int,
    ) -> tuple[HeadingCandidate, ...]:
        ordered = sorted(
            (heading for heading in headings if heading.char_start <= text_length),
            key=lambda item: (
                item.char_start,
                self._ORIGIN_PRIORITY.get(item.origin, 99),
                item.level,
            ),
        )
        result: list[HeadingCandidate] = []
        for heading in ordered:
            if result and (
                abs(result[-1].char_start - heading.char_start) <= 2
                or (
                    _normalized_title(result[-1].title) == _normalized_title(heading.title)
                    and result[-1].page == heading.page
                )
            ):
                current_priority = self._ORIGIN_PRIORITY.get(result[-1].origin, 99)
                new_priority = self._ORIGIN_PRIORITY.get(heading.origin, 99)
                if new_priority < current_priority:
                    result[-1] = heading
                continue
            result.append(heading)
        return tuple(result)
