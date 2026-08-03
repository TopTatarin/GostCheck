"""Shared PDF typography and layout metrics for FMT rules."""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import fitz  # type: ignore[import-untyped]

from normocontrol.extract.base import BoundingBox, PageInfo, TextSpan

MM_TO_PT = 72.0 / 25.4
MARGIN_TOLERANCE_MM = 2.0
MARGINS_MM: dict[str, float] = {
    "left": 30.0,
    "right": 10.0,
    "top": 20.0,
    "bottom": 20.0,
}

TIMES_COMPATIBLE_ALIASES: frozenset[str] = frozenset(
    {
        "Times New Roman",
        "TimesNewRomanPSMT",
        "TimesNewRomanPS-BoldMT",
        "TimesNewRomanPS-ItalicMT",
        "TimesNewRomanPS-BoldItalicMT",
        "Times-Roman",
        "Times-Bold",
        "Times-Italic",
        "Times-BoldItalic",
        "Tempora-Regular",
        "Tempora-Bold",
        "Tempora-Italic",
        "Tempora-BoldItalic",
        "TeXGyreTermes-Regular",
        "TeXGyreTermes-Bold",
        "TeXGyreTermes-Italic",
        "TeXGyreTermes-BoldItalic",
        "LiberationSerif-Regular",
        "LiberationSerif",
        "LiberationSerif-Bold",
        "LiberationSerif-Italic",
        "LiberationSerif-BoldItalic",
    }
)

_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
_PAGE_NUMBER_RE = re.compile(r"^(?:\d+|[ivxlcdm]+)$", re.IGNORECASE)
_MONOSPACED_FONT_RE = re.compile(
    r"courier|consolas|monaco|menlo|mono|typewriter|inconsolata|"
    r"dejavu\s*sans\s*mono|sftt|cmtt",
    re.IGNORECASE,
)
_MATH_FONT_RE = re.compile(
    r"symbol|math|cmmi|cmsy|cmex|msam|msbm|stmary|esint|euler|rsfs|wasy",
    re.IGNORECASE,
)
_COMPUTER_MODERN_ROMAN_RE = re.compile(r"(?:^|[^a-z])cmr\d|computer\s*modern", re.IGNORECASE)
_CODE_CONTEXT_RE = re.compile(
    r"(?:"
    r"//|/\*|\*/|::|->|=>|:=|"
    r"\b(?:class|def|return|import|from|if|else|elif|for|while|try|except|"
    r"function|const|let|var|public|private|protected|void|int|string|bool|"
    r"select|insert|update|delete|where|begin|end)\b|"
    r"\b[A-Za-z_]\w*\s*\(|"
    r"\b[A-Za-z_]\w*\s*=\s*[^=]"
    r")",
    re.IGNORECASE,
)
_CODE_PUNCTUATION = frozenset("{}[]();=<>:+*/#")
_MATH_OPERATOR_RE = re.compile(r"[=±×÷∑∫√∞≤≥≠≈→←∂∆∇+\-*/^]")
_MATH_TOKEN_RE = re.compile(r"^[\d\s.,()[\]{}=±×÷∑∫√∞≤≥≠≈→←∂∆∇+\-*/^_|]+$")
_CAPTION_RE = re.compile(
    r"^\s*(?:рис(?:унок|\.)?|таблица|figure|fig\.?|table)\s*[\dA-ZА-ЯIVX]*",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BodySpanSelection:
    """Reliable body spans and diagnostics for excluded PDF content."""

    spans: tuple[TextSpan, ...]
    significant_chars: int
    invalid_bbox_count: int
    excluded_chars: tuple[tuple[str, int], ...]
    retained_chars: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _VisualLine:
    """Canonical geometry-based line used only for conservative classification."""

    page: int
    items: tuple[tuple[int, TextSpan], ...]

    @property
    def y0(self) -> float:
        return min(span.bbox.y0 for _, span in self.items)

    @property
    def y1(self) -> float:
        return max(span.bbox.y1 for _, span in self.items)

    @property
    def x0(self) -> float:
        return min(span.bbox.x0 for _, span in self.items)

    @property
    def x1(self) -> float:
        return max(span.bbox.x1 for _, span in self.items)


@dataclass(frozen=True, slots=True)
class MarginViolation:
    """One measurable non-marginal span outside the allowed body bounds."""

    span: TextSpan
    page: PageInfo
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class MarginCheckResult:
    """Deterministic result of separating body content from marginalia."""

    content_spans: tuple[TextSpan, ...]
    violations: tuple[MarginViolation, ...]
    measured_pages: tuple[int, ...]
    invalid_bbox_count: int
    excluded_counts: tuple[tuple[str, int], ...]
    max_observed: MarginViolation | None


@dataclass(frozen=True, slots=True)
class PdfLayoutObject:
    """A path-free image or vector-object measurement read by PyMuPDF."""

    page: int
    bbox: BoundingBox
    kind: str
    signature: str


@dataclass(frozen=True, slots=True)
class LayoutMarginViolation:
    """One image or vector object outside the allowed body bounds."""

    item: PdfLayoutObject
    page: PageInfo
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class LayoutMarginCheckResult:
    """Margin result for non-text PDF objects."""

    violations: tuple[LayoutMarginViolation, ...]
    excluded_counts: tuple[tuple[str, int], ...]
    max_observed: LayoutMarginViolation | None


def normalize_pdf_font_name(font: str | None) -> str:
    """Strip a standard PDF subset prefix and normalize family punctuation."""
    if not font:
        return ""
    without_subset = _SUBSET_PREFIX_RE.sub("", font.strip())
    return re.sub(r"[^0-9a-z]+", "", without_subset.casefold())


def display_pdf_font_name(font: str | None) -> str:
    """Return a path-safe, subset-free font name for diagnostics."""
    if not font:
        return "<unknown>"
    return _SUBSET_PREFIX_RE.sub("", font.strip()) or "<unknown>"


def is_times_new_roman(
    font: str | None,
    *,
    aliases: Collection[str] = TIMES_COMPATIBLE_ALIASES,
) -> bool:
    """Return whether a PDF font exactly matches an explicit compatible alias."""
    normalized = normalize_pdf_font_name(font)
    if not normalized:
        return False
    return normalized in {normalize_pdf_font_name(alias) for alias in aliases}


def span_is_bold(span: TextSpan) -> bool:
    """Detect bold spans from PyMuPDF flags or font name."""
    if span.flags is not None and span.flags & 16:
        return True
    return bool(span.font and "bold" in span.font.casefold())


def significant_character_count(text: str) -> int:
    """Count visible, non-whitespace characters used as metric weights."""
    return sum(
        1 for char in text if not char.isspace() and not unicodedata.category(char).startswith("C")
    )


def bbox_is_reliable(bbox: BoundingBox) -> bool:
    """Return whether a bbox has a positive finite area."""
    return (
        all(math.isfinite(value) for value in (bbox.x0, bbox.y0, bbox.x1, bbox.y1))
        and bbox.x1 > bbox.x0
        and bbox.y1 > bbox.y0
    )


def body_spans(spans: tuple[TextSpan, ...]) -> tuple[TextSpan, ...]:
    """Keep spans that look like text rather than tiny extraction artifacts."""
    return tuple(
        span
        for span in spans
        if span.font_size and span.font_size > 0 and significant_character_count(span.text) >= 2
    )


def _metric_page(page: PageInfo) -> PageInfo:
    if page.rotation not in {90, 270}:
        return page
    return page.model_copy(
        update={
            "width": page.height,
            "height": page.width,
            "rotation": 0,
        }
    )


def _normalized_repeated_text(text: str) -> str:
    words = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    return " ".join(re.sub(r"\d+", "#", word) for word in words)


def _bbox_marginal_zone(
    bbox: BoundingBox,
    page: PageInfo,
    *,
    nominal_height: float,
) -> str | None:
    metric_page = _metric_page(page)
    _, _, top, bottom = margin_bounds(metric_page)
    item_height = max(bbox.y1 - bbox.y0, nominal_height, 8.0)
    if bbox.y1 <= top + item_height * 1.5:
        return "header"
    if bbox.y0 >= bottom - item_height * 1.5:
        return "footer"
    return None


def _marginal_zone(span: TextSpan, page: PageInfo) -> str | None:
    return _bbox_marginal_zone(
        span.bbox,
        page,
        nominal_height=span.font_size or 0.0,
    )


def classify_marginal_spans(
    spans: tuple[TextSpan, ...],
    pages: tuple[PageInfo, ...],
    *,
    excluded_pages: frozenset[int] = frozenset(),
) -> dict[int, str]:
    """Classify deterministic page numbers and repeated header/footer spans."""
    page_by_number = {page.number: page for page in pages if page.number not in excluded_pages}
    classified: dict[int, str] = {}
    repeated: dict[tuple[str, str], list[tuple[int, int, float]]] = defaultdict(list)

    for index, span in enumerate(spans):
        page = page_by_number.get(span.page)
        if page is None or not bbox_is_reliable(span.bbox):
            continue
        zone = _marginal_zone(span, page)
        if zone is None or significant_character_count(span.text) < 1:
            continue
        metric_page = _metric_page(page)
        left, right, _, bottom = margin_bounds(metric_page)
        stripped = span.text.strip()
        if (
            zone == "footer"
            and _PAGE_NUMBER_RE.fullmatch(stripped) is not None
            and span.bbox.y0 >= bottom - max(span.font_size or 0.0, 8.0)
            and span.bbox.x0 >= left
            and span.bbox.x1 <= right
        ):
            classified[index] = "page_number"
            continue
        normalized = _normalized_repeated_text(stripped)
        if normalized:
            relative_y = span.bbox.y0 / metric_page.height
            repeated[(zone, normalized)].append((index, span.page, relative_y))

    required_pages = max(2, math.ceil(len(page_by_number) * 0.5))
    for (zone, _), candidates in repeated.items():
        page_numbers = {item[1] for item in candidates}
        relative_positions = [item[2] for item in candidates]
        if (
            len(page_numbers) >= required_pages
            and max(relative_positions) - min(relative_positions) <= 0.025
        ):
            for index, _, _ in candidates:
                classified[index] = f"repeated_{zone}"
    return classified


def _span_is_monospace(span: TextSpan) -> bool:
    """Use PDF metadata or an explicit family hint, never a family hint alone."""
    return bool(
        (span.flags is not None and span.flags & 8)
        or (span.font and _MONOSPACED_FONT_RE.search(span.font))
    )


def _font_is_math_specific(font: str | None) -> bool:
    return bool(font and _MATH_FONT_RE.search(font))


def _font_is_computer_modern_roman(font: str | None) -> bool:
    return bool(font and _COMPUTER_MODERN_ROMAN_RE.search(font))


def _canonical_span_key(item: tuple[int, TextSpan]) -> tuple[object, ...]:
    _, span = item
    return (
        span.page,
        span.bbox.y0,
        span.bbox.x0,
        span.bbox.y1,
        span.bbox.x1,
        span.font or "",
        span.font_size or 0.0,
        span.text,
    )


def _same_visual_line(left: TextSpan, right: TextSpan) -> bool:
    overlap = min(left.bbox.y1, right.bbox.y1) - max(left.bbox.y0, right.bbox.y0)
    minimum_height = min(
        left.bbox.y1 - left.bbox.y0,
        right.bbox.y1 - right.bbox.y0,
    )
    if overlap >= minimum_height * 0.35:
        return True
    left_center = (left.bbox.y0 + left.bbox.y1) / 2.0
    right_center = (right.bbox.y0 + right.bbox.y1) / 2.0
    nominal_size = max(left.font_size or 0.0, right.font_size or 0.0, 8.0)
    return abs(left_center - right_center) <= nominal_size * 0.45


def _visual_lines(items: Iterable[tuple[int, TextSpan]]) -> tuple[_VisualLine, ...]:
    by_page: dict[int, list[tuple[int, TextSpan]]] = defaultdict(list)
    for item in sorted(items, key=_canonical_span_key):
        by_page[item[1].page].append(item)

    lines: list[_VisualLine] = []
    for page in sorted(by_page):
        page_lines: list[list[tuple[int, TextSpan]]] = []
        for item in by_page[page]:
            matching = next(
                (
                    line
                    for line in reversed(page_lines)
                    if any(_same_visual_line(item[1], existing[1]) for existing in line)
                ),
                None,
            )
            if matching is None:
                page_lines.append([item])
            else:
                matching.append(item)
        lines.extend(
            _VisualLine(
                page=page,
                items=tuple(sorted(line, key=_canonical_span_key)),
            )
            for line in page_lines
        )
    return tuple(sorted(lines, key=lambda line: (line.page, line.y0, line.x0)))


def _line_text(line: _VisualLine) -> str:
    parts: list[str] = []
    previous: TextSpan | None = None
    for _, span in line.items:
        if previous is not None:
            gap = span.bbox.x0 - previous.bbox.x1
            if gap > max(span.font_size or 0.0, previous.font_size or 0.0, 8.0) * 0.5:
                parts.append(" ")
        parts.append(span.text)
        previous = span
    return "".join(parts)


def _line_chars(line: _VisualLine) -> int:
    return sum(significant_character_count(span.text) for _, span in line.items)


def _line_dominant_font(line: _VisualLine) -> str:
    weights: Counter[str] = Counter()
    for _, span in line.items:
        weights[normalize_pdf_font_name(span.font)] += significant_character_count(span.text)
    if not weights:
        return ""
    return min(weights, key=lambda font: (-weights[font], font))


def _line_monospace_ratio(line: _VisualLine) -> float:
    total = _line_chars(line)
    if not total:
        return 0.0
    mono = sum(
        significant_character_count(span.text) for _, span in line.items if _span_is_monospace(span)
    )
    return mono / total


def _line_bold_ratio(line: _VisualLine) -> float:
    total = _line_chars(line)
    if not total:
        return 0.0
    bold = sum(
        significant_character_count(span.text) for _, span in line.items if span_is_bold(span)
    )
    return bold / total


def _code_context_score(text: str) -> int:
    matches = len(_CODE_CONTEXT_RE.findall(text))
    punctuation = sum(char in _CODE_PUNCTUATION for char in text)
    return matches + int(punctuation >= 2) + int(punctuation >= 5)


def _lines_are_adjacent(left: _VisualLine, right: _VisualLine) -> bool:
    if left.page != right.page:
        return False
    nominal_height = max(left.y1 - left.y0, right.y1 - right.y0, 8.0)
    vertical_gap = right.y0 - left.y1
    return -nominal_height * 0.25 <= vertical_gap <= nominal_height * 1.5


def _listing_indexes(lines: tuple[_VisualLine, ...]) -> set[int]:
    candidates: list[_VisualLine] = []
    for line in lines:
        has_monospace_metadata = _line_monospace_ratio(line) >= 0.8
        if _line_chars(line) and has_monospace_metadata:
            candidates.append(line)

    runs: list[list[_VisualLine]] = []
    for line in candidates:
        if (
            runs
            and _lines_are_adjacent(runs[-1][-1], line)
            and abs(runs[-1][0].x0 - line.x0) <= 36.0
            and _line_dominant_font(runs[-1][0]) == _line_dominant_font(line)
        ):
            runs[-1].append(line)
        else:
            runs.append([line])

    classified: set[int] = set()
    for run in runs:
        code_score = sum(_code_context_score(_line_text(line)) for line in run)
        chars = sum(_line_chars(line) for line in run)
        if len(run) < 3 or code_score < 2 or chars < 12:
            continue
        classified.update(index for line in run for index, _ in line.items)
    return classified


def _line_cell_starts(line: _VisualLine) -> tuple[float, ...]:
    starts: list[float] = []
    previous: TextSpan | None = None
    for _, span in line.items:
        if significant_character_count(span.text) < 1:
            continue
        if previous is None:
            starts.append(span.bbox.x0)
        else:
            nominal_size = max(previous.font_size or 0.0, span.font_size or 0.0, 8.0)
            if span.bbox.x0 - previous.bbox.x1 > nominal_size * 1.5:
                starts.append(span.bbox.x0)
        previous = span
    return tuple(starts)


def _cell_starts_align(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    matches = sum(any(abs(value - candidate) <= 12.0 for candidate in right) for value in left)
    return matches >= 2


def _table_indexes(lines: tuple[_VisualLine, ...]) -> set[int]:
    candidates = [(line, _line_cell_starts(line)) for line in lines]
    candidates = [(line, starts) for line, starts in candidates if len(starts) >= 2]
    runs: list[list[tuple[_VisualLine, tuple[float, ...]]]] = []
    for candidate in candidates:
        line, starts = candidate
        if (
            runs
            and _lines_are_adjacent(runs[-1][-1][0], line)
            and _cell_starts_align(runs[-1][-1][1], starts)
        ):
            runs[-1].append(candidate)
        else:
            runs.append([candidate])

    classified: set[int] = set()
    for run in runs:
        numeric_rows = sum(any(char.isdigit() for char in _line_text(line)) for line, _ in run)
        monospace_rows = sum(_line_monospace_ratio(line) >= 0.8 for line, _ in run)
        if len(run) < 3 or numeric_rows < 2 or monospace_rows >= len(run) * 0.5:
            continue
        classified.update(index for line, _ in run for index, _ in line.items)
    return classified


def _formula_indexes(lines: tuple[_VisualLine, ...]) -> set[int]:
    classified: set[int] = set()
    for line in lines:
        math_specific = [
            (index, span) for index, span in line.items if _font_is_math_specific(span.font)
        ]
        generic_cm = [
            (index, span) for index, span in line.items if _font_is_computer_modern_roman(span.font)
        ]
        text = _line_text(line)
        operators = len(_MATH_OPERATOR_RE.findall(text))
        math_tokens = [
            (index, span)
            for index, span in line.items
            if _MATH_TOKEN_RE.fullmatch(span.text.strip()) is not None
        ]
        has_specific_context = bool(math_specific) and (len(math_specific) >= 2 or operators >= 1)
        has_generic_display_context = (
            not math_specific
            and len(generic_cm) >= 2
            and operators >= 1
            and sum(significant_character_count(span.text) for _, span in math_tokens)
            >= _line_chars(line) * 0.6
        )
        if not has_specific_context and not has_generic_display_context:
            continue
        classified.update(index for index, _ in math_specific)
        classified.update(index for index, _ in generic_cm)
        classified.update(index for index, _ in math_tokens)
    return classified


def _dominant_font_size(spans: Iterable[TextSpan]) -> float | None:
    weights: Counter[float] = Counter()
    for span in spans:
        if span.font_size is None or span.font_size <= 0:
            continue
        bucket = round(span.font_size * 2.0) / 2.0
        weights[bucket] += significant_character_count(span.text)
    if not weights:
        return None
    return min(weights, key=lambda size: (-weights[size], size))


def select_body_spans(
    spans: tuple[TextSpan, ...],
    pages: tuple[PageInfo, ...],
    *,
    excluded_pages: frozenset[int] = frozenset(),
) -> BodySpanSelection:
    """Separate reliable body text from headings, code, formulae and marginalia.

    ``excluded_pages`` is intentionally supplied only by the conservative page-role
    sidecar.  Callers must never infer it from a page number alone.
    """
    marginal = classify_marginal_spans(spans, pages, excluded_pages=excluded_pages)
    candidates: list[tuple[int, TextSpan]] = []
    excluded: Counter[str] = Counter()
    retained: Counter[str] = Counter()
    invalid_bbox_count = 0

    for index, span in enumerate(spans):
        chars = significant_character_count(span.text)
        if span.page in excluded_pages:
            excluded["service_page"] += chars
            continue
        if chars < 1 or span.font_size is None or span.font_size <= 0:
            excluded["artifact"] += chars
            continue
        if not bbox_is_reliable(span.bbox):
            invalid_bbox_count += 1
            excluded["invalid_bbox"] += chars
            continue
        marginal_kind = marginal.get(index)
        if marginal_kind is not None:
            excluded[marginal_kind] += chars
            continue
        candidates.append((index, span))

    lines = _visual_lines(candidates)
    body_size = _dominant_font_size(span for _, span in candidates)
    classified: dict[int, str] = {}

    for line in lines:
        line_text = _line_text(line)
        if _CAPTION_RE.match(line_text) is not None and _line_chars(line) <= 240:
            for index, _ in line.items:
                classified[index] = "caption"

    for index in _table_indexes(lines):
        classified.setdefault(index, "table")
    for index in _listing_indexes(lines):
        classified.setdefault(index, "listing")
    for index in _formula_indexes(lines):
        classified.setdefault(index, "formula")

    for line_index, line in enumerate(lines):
        line_sizes = [
            span.font_size or 0.0
            for _, span in line.items
            if significant_character_count(span.text)
        ]
        previous = lines[line_index - 1] if line_index > 0 else None
        following = lines[line_index + 1] if line_index + 1 < len(lines) else None
        previous_distance = (
            line.y0 - previous.y0 if previous is not None and previous.page == line.page else None
        )
        following_distance = (
            following.y0 - line.y0
            if following is not None and following.page == line.page
            else None
        )
        isolated_bold_line = (
            body_size is not None
            and _line_bold_ratio(line) >= 0.8
            and any(
                distance is not None and distance > body_size * 2.0
                for distance in (previous_distance, following_distance)
            )
        )
        if (
            body_size is not None
            and line_sizes
            and _line_chars(line) <= 160
            and (statistics.median(line_sizes) > body_size + 0.75 or isolated_bold_line)
        ):
            for index, _ in line.items:
                classified.setdefault(index, "heading")

    selected: list[tuple[int, TextSpan]] = []
    for index, span in candidates:
        chars = significant_character_count(span.text)
        category = classified.get(index)
        if category is not None:
            excluded[category] += chars
            continue
        selected.append((index, span))
        if _span_is_monospace(span):
            retained["inline_code"] += chars
        if _font_is_math_specific(span.font) or _font_is_computer_modern_roman(span.font):
            retained["unconfirmed_math"] += chars

    ordered_selected = tuple(span for _, span in sorted(selected, key=_canonical_span_key))
    significant_chars = sum(significant_character_count(span.text) for span in ordered_selected)
    return BodySpanSelection(
        spans=ordered_selected,
        significant_chars=significant_chars,
        invalid_bbox_count=invalid_bbox_count,
        excluded_chars=tuple(sorted(excluded.items())),
        retained_chars=tuple(sorted(retained.items())),
    )


def heading_spans(spans: tuple[TextSpan, ...]) -> tuple[TextSpan, ...]:
    """Approximate heading spans as larger-than-body or bold lines."""
    candidates = body_spans(spans)
    if not candidates:
        return ()
    body_size = statistics.median(span.font_size or 0.0 for span in candidates)
    threshold = body_size * 1.05
    return tuple(
        span
        for span in candidates
        if (span.font_size and span.font_size >= threshold) or span_is_bold(span)
    )


def _character_weighted_ratio(
    spans: Iterable[TextSpan],
    predicate: Callable[[TextSpan], bool],
) -> float:
    matched = 0
    total = 0
    for span in spans:
        weight = significant_character_count(span.text)
        total += weight
        if predicate(span):
            matched += weight
    return matched / total if total else 0.0


def font_size_match_ratio(
    spans: Iterable[TextSpan],
    *,
    expected_pt: float,
    tolerance_pt: float = 0.5,
) -> float:
    """Share of significant characters whose font size matches the expected value."""
    return _character_weighted_ratio(
        spans,
        lambda span: (
            span.font_size is not None and abs(span.font_size - expected_pt) <= tolerance_pt
        ),
    )


def times_new_roman_ratio(
    spans: Iterable[TextSpan],
    *,
    aliases: Collection[str] = TIMES_COMPATIBLE_ALIASES,
) -> float:
    """Share of significant characters using an explicitly compatible font."""
    return _character_weighted_ratio(
        spans,
        lambda span: is_times_new_roman(span.font, aliases=aliases),
    )


def top_fonts(
    spans: Iterable[TextSpan],
    *,
    limit: int = 3,
) -> tuple[tuple[str, int], ...]:
    """Return subset-free font names ranked by significant character count."""
    weights: Counter[str] = Counter()
    for span in spans:
        weights[display_pdf_font_name(span.font)] += significant_character_count(span.text)
    return tuple(sorted(weights.items(), key=lambda item: (-item[1], item[0].casefold())))[:limit]


def top_font_sizes(
    spans: Iterable[TextSpan],
    *,
    limit: int = 3,
) -> tuple[tuple[float, int], ...]:
    """Return font sizes ranked by significant-character weight."""
    weights: Counter[float] = Counter()
    for span in spans:
        if span.font_size is None or span.font_size <= 0:
            continue
        weights[round(span.font_size, 1)] += significant_character_count(span.text)
    return tuple(sorted(weights.items(), key=lambda item: (-item[1], item[0])))[:limit]


def typography_mismatch_pages(
    spans: Iterable[TextSpan],
    *,
    expected_pt: float,
    tolerance_pt: float = 0.5,
    limit: int = 3,
) -> tuple[tuple[int, int], ...]:
    """Rank pages by characters that miss either the font or size requirement."""
    weights: Counter[int] = Counter()
    for span in spans:
        size_matches = (
            span.font_size is not None and abs(span.font_size - expected_pt) <= tolerance_pt
        )
        if not is_times_new_roman(span.font) or not size_matches:
            weights[span.page] += significant_character_count(span.text)
    return tuple(sorted(weights.items(), key=lambda item: (-item[1], item[0])))[:limit]


def typography_mismatch_samples(
    spans: Iterable[TextSpan],
    *,
    expected_pt: float,
    tolerance_pt: float = 0.5,
    limit: int = 3,
) -> tuple[tuple[int, BoundingBox, str], ...]:
    """Return deterministic coordinate/hash samples without thesis fragments."""
    mismatches: list[TextSpan] = []
    for span in spans:
        size_matches = (
            span.font_size is not None and abs(span.font_size - expected_pt) <= tolerance_pt
        )
        if not is_times_new_roman(span.font) or not size_matches:
            mismatches.append(span)
    ranked = sorted(
        mismatches,
        key=lambda span: (
            span.page,
            span.bbox.y0,
            span.bbox.x0,
            span.bbox.y1,
            span.bbox.x1,
            span.font or "",
            span.text,
        ),
    )
    return tuple(
        (
            span.page,
            span.bbox,
            sha256(span.text.encode("utf-8")).hexdigest()[:12],
        )
        for span in ranked[:limit]
    )


def example_pages(
    spans: Iterable[TextSpan],
    *,
    limit: int = 3,
) -> tuple[int, ...]:
    """Return deterministic example pages ranked by measured body characters."""
    weights: Counter[int] = Counter()
    for span in spans:
        weights[span.page] += significant_character_count(span.text)
    ranked = sorted(weights, key=lambda page: (-weights[page], page))
    return tuple(sorted(ranked[:limit]))


def page_text_bbox(spans: Iterable[TextSpan], page_number: int) -> BoundingBox | None:
    """Union bbox of all reliable spans on one page."""
    page_spans = [
        span for span in spans if span.page == page_number and bbox_is_reliable(span.bbox)
    ]
    if not page_spans:
        return None
    return BoundingBox(
        x0=min(span.bbox.x0 for span in page_spans),
        y0=min(span.bbox.y0 for span in page_spans),
        x1=max(span.bbox.x1 for span in page_spans),
        y1=max(span.bbox.y1 for span in page_spans),
    )


def margin_bounds(page: PageInfo) -> tuple[float, float, float, float]:
    """Return left, right, top, bottom bounds for printable text in PDF points."""
    tolerance = MARGIN_TOLERANCE_MM * MM_TO_PT
    width = page.width if page.rotation not in {90, 270} else page.height
    height = page.height if page.rotation not in {90, 270} else page.width
    left = MARGINS_MM["left"] * MM_TO_PT - tolerance
    right = width - MARGINS_MM["right"] * MM_TO_PT + tolerance
    top = MARGINS_MM["top"] * MM_TO_PT - tolerance
    bottom = height - MARGINS_MM["bottom"] * MM_TO_PT + tolerance
    return left, right, top, bottom


def bbox_margin_overflow(
    bbox: BoundingBox,
    page: PageInfo,
) -> tuple[float, float, float, float]:
    """Return left, right, top, and bottom overflow in PDF points."""
    left, right, top, bottom = margin_bounds(page)
    return (
        max(0.0, left - bbox.x0),
        max(0.0, bbox.x1 - right),
        max(0.0, top - bbox.y0),
        max(0.0, bbox.y1 - bottom),
    )


def bbox_within_margins(
    bbox: BoundingBox,
    page: PageInfo,
    *,
    geometry_tolerance_pt: float = 0.0,
) -> bool:
    """Return whether a bbox fits inside the bounds plus coordinate tolerance."""
    if not math.isfinite(geometry_tolerance_pt) or geometry_tolerance_pt < 0:
        raise ValueError("geometry_tolerance_pt must be finite and non-negative")
    delta_pt = max(bbox_margin_overflow(bbox, page))
    return delta_pt <= geometry_tolerance_pt or math.isclose(
        delta_pt,
        geometry_tolerance_pt,
        rel_tol=0.0,
        abs_tol=1e-9,
    )


def check_body_margins(
    spans: tuple[TextSpan, ...],
    pages: tuple[PageInfo, ...],
    *,
    geometry_tolerance_pt: float = 0.0,
    excluded_pages: frozenset[int] = frozenset(),
) -> MarginCheckResult:
    """Measure non-marginal content without hiding the whole page footer zone."""
    page_by_number = {page.number: _metric_page(page) for page in pages}
    marginal = classify_marginal_spans(spans, pages, excluded_pages=excluded_pages)
    excluded: Counter[str] = Counter()
    content: list[TextSpan] = []
    violations: list[MarginViolation] = []
    invalid_bbox_count = 0
    max_observed: MarginViolation | None = None
    max_observed_delta = -1.0

    for index, span in enumerate(spans):
        chars = significant_character_count(span.text)
        if span.page in excluded_pages:
            excluded["service_page"] += max(chars, 1)
            continue
        if chars < 2 and index not in marginal:
            continue
        marginal_kind = marginal.get(index)
        if marginal_kind is not None:
            excluded[marginal_kind] += max(chars, 1)
            continue
        page = page_by_number.get(span.page)
        if page is None:
            invalid_bbox_count += 1
            continue
        if not bbox_is_reliable(span.bbox):
            invalid_bbox_count += 1
            continue
        content.append(span)
        observation = MarginViolation(
            span=span,
            page=page,
            bounds=margin_bounds(page),
        )
        observed_delta = max(bbox_margin_overflow(span.bbox, page))
        if observed_delta > max_observed_delta:
            max_observed = observation
            max_observed_delta = observed_delta
        if not bbox_within_margins(
            span.bbox,
            page,
            geometry_tolerance_pt=geometry_tolerance_pt,
        ):
            violations.append(observation)

    return MarginCheckResult(
        content_spans=tuple(content),
        violations=tuple(violations),
        measured_pages=tuple(sorted({span.page for span in content})),
        invalid_bbox_count=invalid_bbox_count,
        excluded_counts=tuple(sorted(excluded.items())),
        max_observed=max_observed,
    )


def _layout_bbox(raw_bbox: object) -> BoundingBox | None:
    try:
        sequence = cast(list[float] | tuple[float, ...], raw_bbox)
        values = tuple(float(value) for value in sequence)
    except (TypeError, ValueError):
        return None
    if len(values) != 4:
        return None
    bbox = BoundingBox(x0=values[0], y0=values[1], x1=values[2], y1=values[3])
    return bbox if bbox_is_reliable(bbox) else None


def extract_pdf_layout_objects(pdf_path: Path | None) -> tuple[PdfLayoutObject, ...]:
    """Read image and meaningful vector bboxes without changing bundle contracts."""
    if pdf_path is None or not pdf_path.is_file():
        return ()
    objects: list[PdfLayoutObject] = []
    try:
        with fitz.open(pdf_path) as document:
            for page_index, page in enumerate(document, start=1):
                image_info = cast(list[dict[str, Any]], page.get_image_info(hashes=True))
                for image in image_info:
                    bbox = _layout_bbox(image.get("bbox"))
                    if bbox is None:
                        continue
                    digest = image.get("digest")
                    signature = (
                        bytes(digest).hex()
                        if isinstance(digest, (bytes, bytearray))
                        else f"{bbox.x1 - bbox.x0:.1f}x{bbox.y1 - bbox.y0:.1f}"
                    )
                    objects.append(
                        PdfLayoutObject(
                            page=page_index,
                            bbox=bbox,
                            kind="image",
                            signature=signature,
                        )
                    )
                drawings = cast(list[dict[str, Any]], page.get_drawings())
                for drawing in drawings:
                    bbox = _layout_bbox(drawing.get("rect"))
                    if bbox is None or bbox.x1 - bbox.x0 <= 2.0 or bbox.y1 - bbox.y0 <= 2.0:
                        continue
                    signature = (
                        f"{bbox.x1 - bbox.x0:.1f}x{bbox.y1 - bbox.y0:.1f}:"
                        f"{len(cast(list[object], drawing.get('items', [])))}"
                    )
                    objects.append(
                        PdfLayoutObject(
                            page=page_index,
                            bbox=bbox,
                            kind="vector",
                            signature=signature,
                        )
                    )
    except (OSError, RuntimeError, ValueError):
        return ()
    return tuple(objects)


def check_layout_object_margins(
    objects: tuple[PdfLayoutObject, ...],
    pages: tuple[PageInfo, ...],
    *,
    geometry_tolerance_pt: float = 0.0,
    excluded_pages: frozenset[int] = frozenset(),
) -> LayoutMarginCheckResult:
    """Check image/vector bounds while excluding only repeated marginal objects."""
    page_by_number = {
        page.number: _metric_page(page) for page in pages if page.number not in excluded_pages
    }
    repetitions: dict[tuple[str, str, str], list[PdfLayoutObject]] = defaultdict(list)
    marginal: set[PdfLayoutObject] = set()
    required_pages = max(2, math.ceil(len(page_by_number) * 0.5))

    for item in objects:
        page = page_by_number.get(item.page)
        if page is None:
            continue
        zone = _bbox_marginal_zone(item.bbox, page, nominal_height=8.0)
        if zone is not None:
            repetitions[(zone, item.kind, item.signature)].append(item)
    for candidates in repetitions.values():
        if len({item.page for item in candidates}) >= required_pages:
            relative_y = [item.bbox.y0 / page_by_number[item.page].height for item in candidates]
            if max(relative_y) - min(relative_y) <= 0.025:
                marginal.update(candidates)

    excluded: Counter[str] = Counter()
    violations: list[LayoutMarginViolation] = []
    max_observed: LayoutMarginViolation | None = None
    max_observed_delta = -1.0
    for item in objects:
        if item.page in excluded_pages:
            excluded[f"service_page_{item.kind}"] += 1
            continue
        if item in marginal:
            excluded[f"repeated_{item.kind}_marginalia"] += 1
            continue
        page = page_by_number.get(item.page)
        if page is not None:
            observation = LayoutMarginViolation(
                item=item,
                page=page,
                bounds=margin_bounds(page),
            )
            observed_delta = max(bbox_margin_overflow(item.bbox, page))
            if observed_delta > max_observed_delta:
                max_observed = observation
                max_observed_delta = observed_delta
            if not bbox_within_margins(
                item.bbox,
                page,
                geometry_tolerance_pt=geometry_tolerance_pt,
            ):
                violations.append(observation)
    return LayoutMarginCheckResult(
        violations=tuple(violations),
        excluded_counts=tuple(sorted(excluded.items())),
        max_observed=max_observed,
    )


def median_line_spacing_ratio(spans: tuple[TextSpan, ...]) -> float | None:
    """Estimate line spacing as median baseline delta divided by body font size."""
    by_page: dict[int, list[TextSpan]] = {}
    for span in body_spans(spans):
        by_page.setdefault(span.page, []).append(span)
    ratios: list[float] = []
    for page_spans in by_page.values():
        lines: dict[float, list[TextSpan]] = {}
        for span in page_spans:
            key = round(span.bbox.y0, 1)
            lines.setdefault(key, []).append(span)
        ordered = sorted(lines.items())
        if len(ordered) < 2:
            continue
        body_size = statistics.median(
            span.font_size or 0.0 for _, line_spans in ordered for span in line_spans
        )
        if body_size <= 0:
            continue
        baselines = [y for y, _ in ordered]
        deltas = [baselines[index + 1] - baselines[index] for index in range(len(baselines) - 1)]
        positive = [delta for delta in deltas if delta > 0]
        if not positive:
            continue
        ratios.append(statistics.median(positive) / body_size)
    if not ratios:
        return None
    return statistics.median(ratios)
