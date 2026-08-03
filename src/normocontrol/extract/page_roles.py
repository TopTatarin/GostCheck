"""Conservative, path-safe classification of PDF page roles.

The result is deliberately an internal sidecar rather than a ``DocumentBundle``
field: adding a role classifier must not change the published extraction or
report schemas. Only high-confidence service pages are eligible for exclusion.
Unknown pages are always retained for formal checks.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from normocontrol.extract.base import (
    HeadingCandidate,
    PageInfo,
    Section,
    SectionKind,
    TextSpan,
)


class DocumentKind(StrEnum):
    """Internal input classification; it never changes an exit code by itself."""

    THESIS = "thesis"
    SERVICE_DOCUMENT = "service_document"
    METHODICAL_DOCUMENT = "methodical_document"
    UNKNOWN = "unknown"


class PageRole(StrEnum):
    """Page roles used to scope layout metrics and semantic batching."""

    TITLE = "title"
    APPROVAL = "approval"
    ASSIGNMENT = "assignment"
    CALENDAR_PLAN = "calendar_plan"
    REVIEW = "review"
    ABSTRACT = "abstract"
    CONTENTS = "contents"
    MAIN_TEXT = "main_text"
    BIBLIOGRAPHY = "bibliography"
    APPENDIX = "appendix"
    UNKNOWN = "unknown"


class RoleConfidence(StrEnum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class PageRoleAssessment:
    """Path-safe page classification with reason codes, never source excerpts."""

    page: int
    role: PageRole
    confidence: RoleConfidence
    reasons: tuple[str, ...]

    @property
    def excludes_service_metrics(self) -> bool:
        return self.confidence is RoleConfidence.HIGH and self.role in {
            PageRole.TITLE,
            PageRole.APPROVAL,
            PageRole.ASSIGNMENT,
            PageRole.CALENDAR_PLAN,
            PageRole.REVIEW,
        }


@dataclass(frozen=True, slots=True)
class PageRoleAnalysis:
    document_kind: DocumentKind
    pages: tuple[PageRoleAssessment, ...]
    main_start_page: int | None

    @property
    def excluded_service_pages(self) -> frozenset[int]:
        return frozenset(item.page for item in self.pages if item.excludes_service_metrics)

    def evidence_summary(self) -> str:
        """Return compact diagnostics without paths, names, or document text."""
        excluded = tuple(item for item in self.pages if item.excludes_service_metrics)
        page_text = _page_ranges(item.page for item in excluded)
        role_pages: dict[PageRole, list[int]] = {}
        for item in excluded:
            role_pages.setdefault(item.role, []).append(item.page)
        roles = ",".join(
            f"{role.value}:{_page_ranges(pages)}"
            for role, pages in sorted(role_pages.items(), key=lambda item: item[0].value)
        )
        return (
            f"document_kind={self.document_kind.value}; main_start_page="
            f"{self.main_start_page if self.main_start_page is not None else 'unknown'}; "
            f"service_pages={page_text}; service_roles={roles or 'none'}"
        )


_WORD_RE = re.compile(r"\w+", re.UNICODE)
_INTRODUCTION = frozenset({"введение", "introduction"})
_CONTENTS = frozenset({"содержание", "оглавление", "contents", "table of contents"})
_NON_SERVICE_HEADING_ROLES: tuple[tuple[PageRole, frozenset[str]], ...] = (
    (PageRole.ABSTRACT, frozenset({"аннотация", "реферат", "abstract"})),
    (PageRole.CONTENTS, _CONTENTS),
    (
        PageRole.BIBLIOGRAPHY,
        frozenset({"библиография", "список литературы", "references"}),
    ),
    (PageRole.APPENDIX, frozenset({"приложение", "appendix"})),
)


def _page_ranges(pages: Iterable[int]) -> str:
    """Return stable compact page ranges for bounded evidence."""
    ordered = sorted(set(pages))
    if not ordered:
        return "none"
    ranges: list[str] = []
    start = previous = ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join(_WORD_RE.findall(value))


def _contains_all(text: str, *anchors: str) -> bool:
    return all(_normalized(anchor) in text for anchor in anchors)


def _page_texts(spans: tuple[TextSpan, ...]) -> dict[int, str]:
    grouped: dict[int, list[TextSpan]] = {}
    for span in spans:
        grouped.setdefault(span.page, []).append(span)
    return {
        page: _normalized(
            " ".join(
                span.text
                for span in sorted(
                    values,
                    key=lambda item: (item.bbox.y0, item.bbox.x0, item.bbox.y1, item.bbox.x1),
                )
            )
        )
        for page, values in grouped.items()
    }


def _body_font_size(spans: tuple[TextSpan, ...]) -> float | None:
    sizes = [span.font_size for span in spans if span.font_size is not None and span.text.strip()]
    return statistics.median(sizes) if sizes else None


def _is_heading_like(span: TextSpan, page: PageInfo | None, body_size: float | None) -> bool:
    """Require visual heading evidence before trusting an exact title string."""
    if page is None or span.bbox.y0 > page.height * 0.45:
        return False
    bold = (span.flags is not None and bool(span.flags & 16)) or (
        span.font is not None and "bold" in span.font.casefold()
    )
    larger_than_body = (
        body_size is not None and span.font_size is not None and span.font_size >= body_size * 1.1
    )
    return bold or larger_than_body


def _heading_titles(
    spans: tuple[TextSpan, ...], pages: tuple[PageInfo, ...], headings: tuple[HeadingCandidate, ...]
) -> dict[int, frozenset[str]]:
    page_by_number = {page.number: page for page in pages}
    body_size = _body_font_size(spans)
    titles: dict[int, set[str]] = {}
    for heading in headings:
        if heading.page is not None:
            titles.setdefault(heading.page, set()).add(_normalized(heading.title))
    for span in spans:
        normalized = _normalized(span.text)
        if normalized and _is_heading_like(span, page_by_number.get(span.page), body_size):
            titles.setdefault(span.page, set()).add(normalized)
    return {page: frozenset(values) for page, values in titles.items()}


def _introduction_page(
    spans: tuple[TextSpan, ...],
    pages: tuple[PageInfo, ...],
    sections: tuple[Section, ...],
    headings: tuple[HeadingCandidate, ...],
    text_by_page: dict[int, str],
) -> int | None:
    """Locate the real introduction, never a contents entry named "Introduction"."""
    section_pages = [
        section.page_start
        for section in sections
        if section.kind is SectionKind.INTRODUCTION and section.page_start is not None
    ]
    if section_pages:
        return min(section_pages)

    heading_pages = [
        heading.page
        for heading in headings
        if heading.page is not None
        and _normalized(heading.title) in _INTRODUCTION
        and not any(anchor in text_by_page.get(heading.page, "") for anchor in _CONTENTS)
    ]
    if heading_pages:
        return min(heading_pages)

    page_by_number = {page.number: page for page in pages}
    body_size = _body_font_size(spans)
    span_pages = [
        span.page
        for span in spans
        if _normalized(span.text) in _INTRODUCTION
        and not any(anchor in text_by_page.get(span.page, "") for anchor in _CONTENTS)
        and _is_heading_like(span, page_by_number.get(span.page), body_size)
    ]
    return min(span_pages) if span_pages else None


def _template_support_count(text: str) -> int:
    """Count independent form-field groups, not repetitions of ordinary words."""
    groups = (
        ("студент", "обучающийся", "исполнитель"),
        ("руководитель", "научный руководитель"),
        ("исходные данные", "исходная информация"),
        ("срок выполнения", "дата выдачи", "дата"),
        ("подпись", "подписи"),
        ("оценка", "отметка", "рецензент"),
    )
    return sum(any(_contains_all(text, anchor) for anchor in group) for group in groups)


def _service_role(
    text: str,
    heading_titles: frozenset[str],
    *,
    before_main: bool,
    has_main: bool,
) -> PageRoleAssessment | None:
    """Classify templates only with independent structural anchors and context."""
    title = (
        _contains_all(text, "выпускная квалификационная работа")
        or _contains_all(text, "graduate qualification work")
        or _contains_all(text, "bachelor thesis")
    )
    title_support = (
        _contains_all(text, "направление подготовки")
        or _contains_all(text, "квалификация")
        or _contains_all(text, "бакалавр")
    )
    assignment_phrase = _contains_all(text, "задание на выполнение") and _contains_all(
        text, "выпускной квалификационной работы"
    )
    assignment_heading = any(
        title in {"задание", "assignment"}
        or title.startswith("задание на выполнение")
        or title.startswith("assignment for")
        for title in heading_titles
    )
    assignment_mention = _contains_all(text, "задани") or _contains_all(text, "assignment")
    approval = _contains_all(text, "утверждаю")
    institution = any(
        _contains_all(text, anchor)
        for anchor in ("министерство", "университет", "институт", "академия")
    )
    calendar = _contains_all(text, "календарный план") and (
        _contains_all(text, "срок выполнения") or _contains_all(text, "этапы выполнения")
    )
    review_heading = bool({"отзыв", "рецензия", "review"} & heading_titles)

    if review_heading and _template_support_count(text) >= 2:
        return PageRoleAssessment(
            0, PageRole.REVIEW, RoleConfidence.HIGH, ("review_heading", "review_form")
        )
    if has_main and not before_main:
        return None
    template_support = _template_support_count(text)
    if ((assignment_phrase or assignment_heading) and template_support >= 2) or (
        assignment_mention and template_support >= 3
    ):
        return PageRoleAssessment(
            0, PageRole.ASSIGNMENT, RoleConfidence.HIGH, ("assignment_template", "front_context")
        )
    if calendar:
        return PageRoleAssessment(
            0, PageRole.CALENDAR_PLAN, RoleConfidence.HIGH, ("calendar_anchor", "front_context")
        )
    if approval and institution and template_support >= 1:
        return PageRoleAssessment(
            0, PageRole.APPROVAL, RoleConfidence.HIGH, ("approval_template", "front_context")
        )
    if title and title_support and institution:
        return PageRoleAssessment(
            0, PageRole.TITLE, RoleConfidence.HIGH, ("title_anchor", "program_anchor")
        )
    return None


def _non_service_role(heading_titles: frozenset[str]) -> PageRole | None:
    for role, titles in _NON_SERVICE_HEADING_ROLES:
        if titles & heading_titles:
            return role
    return None


def analyze_page_roles(
    spans: tuple[TextSpan, ...],
    pages: tuple[PageInfo, ...],
    *,
    sections: tuple[Section, ...] = (),
    headings: tuple[HeadingCandidate, ...] = (),
) -> PageRoleAnalysis:
    """Return deterministic high-precision roles for PDF layout scope.

    Non-service roles are low-confidence and deliberately retained. Their only
    purpose is traceability; a mistaken role must not silence a formal failure.
    """
    if not pages:
        return PageRoleAnalysis(DocumentKind.UNKNOWN, (), None)
    text_by_page = _page_texts(spans)
    heading_titles = _heading_titles(spans, pages, headings)
    main_start = _introduction_page(spans, pages, sections, headings, text_by_page)
    assessments: list[PageRoleAssessment] = []
    for page in sorted(pages, key=lambda item: item.number):
        text = text_by_page.get(page.number, "")
        candidate = _service_role(
            text,
            heading_titles.get(page.number, frozenset()),
            before_main=main_start is None or page.number < main_start,
            has_main=main_start is not None,
        )
        if candidate is not None:
            assessments.append(
                PageRoleAssessment(
                    page.number, candidate.role, candidate.confidence, candidate.reasons
                )
            )
            continue
        non_service = _non_service_role(heading_titles.get(page.number, frozenset()))
        if non_service is not None:
            assessments.append(
                PageRoleAssessment(page.number, non_service, RoleConfidence.LOW, ("heading",))
            )
        elif main_start is not None and page.number >= main_start:
            assessments.append(
                PageRoleAssessment(
                    page.number, PageRole.MAIN_TEXT, RoleConfidence.LOW, ("main_boundary",)
                )
            )
        else:
            assessments.append(
                PageRoleAssessment(
                    page.number, PageRole.UNKNOWN, RoleConfidence.LOW, ("insufficient_signals",)
                )
            )

    excluded = [item for item in assessments if item.excludes_service_metrics]
    if main_start is not None:
        kind = DocumentKind.THESIS
    elif assessments and len(excluded) == len(assessments):
        kind = DocumentKind.SERVICE_DOCUMENT
    elif any(_contains_all(text, "методические рекомендации") for text in text_by_page.values()):
        kind = DocumentKind.METHODICAL_DOCUMENT
    else:
        kind = DocumentKind.UNKNOWN
    return PageRoleAnalysis(kind, tuple(assessments), main_start)
