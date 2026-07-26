"""Shared PDF typography and layout metrics for FMT rules."""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
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
        "Times-Roman",
        "Tempora-Regular",
    }
)

_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
_PAGE_NUMBER_RE = re.compile(r"^(?:\d+|[ivxlcdm]+)$", re.IGNORECASE)
_MONOSPACED_FONT_RE = re.compile(
    r"courier|consolas|monaco|menlo|mono|typewriter|inconsolata|dejavu\s*sans\s*mono",
    re.IGNORECASE,
)
_MATH_FONT_RE = re.compile(
    r"symbol|math|cmmi|cmsy|cmex|msam|msbm|stmary|esint|euler|rsfs|wasy",
    re.IGNORECASE,
)
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
        1
        for char in text
        if not char.isspace() and not unicodedata.category(char).startswith("C")
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
        if span.font_size
        and span.font_size > 0
        and significant_character_count(span.text) >= 2
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
) -> dict[int, str]:
    """Classify deterministic page numbers and repeated header/footer spans."""
    page_by_number = {page.number: page for page in pages}
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

    required_pages = max(2, math.ceil(len(pages) * 0.5))
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


def _font_is_code_or_math(font: str | None) -> str | None:
    if not font:
        return None
    if _MONOSPACED_FONT_RE.search(font):
        return "code"
    if _MATH_FONT_RE.search(font):
        return "formula"
    return None


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
) -> BodySpanSelection:
    """Separate reliable body text from headings, code, formulae and marginalia."""
    marginal = classify_marginal_spans(spans, pages)
    candidates: list[TextSpan] = []
    excluded: Counter[str] = Counter()
    invalid_bbox_count = 0

    for index, span in enumerate(spans):
        chars = significant_character_count(span.text)
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
        content_kind = _font_is_code_or_math(span.font)
        if content_kind is not None:
            excluded[content_kind] += chars
            continue
        candidates.append(span)

    body_size = _dominant_font_size(candidates)
    selected: list[TextSpan] = []
    for span in candidates:
        chars = significant_character_count(span.text)
        size = span.font_size or 0.0
        if body_size is not None and size > body_size + 0.75 and chars <= 160:
            excluded["heading"] += chars
            continue
        if span_is_bold(span) and chars <= 160:
            excluded["heading"] += chars
            continue
        if (
            body_size is not None
            and size < body_size - 0.75
            and _CAPTION_RE.match(span.text) is not None
        ):
            excluded["caption"] += chars
            continue
        selected.append(span)

    significant_chars = sum(significant_character_count(span.text) for span in selected)
    return BodySpanSelection(
        spans=tuple(selected),
        significant_chars=significant_chars,
        invalid_bbox_count=invalid_bbox_count,
        excluded_chars=tuple(sorted(excluded.items())),
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
        span
        for span in spans
        if span.page == page_number and bbox_is_reliable(span.bbox)
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


def bbox_within_margins(bbox: BoundingBox, page: PageInfo) -> bool:
    """Return whether a bbox fits inside the allowed text area."""
    left, right, top, bottom = margin_bounds(page)
    return bbox.x0 >= left and bbox.x1 <= right and bbox.y0 >= top and bbox.y1 <= bottom


def check_body_margins(
    spans: tuple[TextSpan, ...],
    pages: tuple[PageInfo, ...],
) -> MarginCheckResult:
    """Measure non-marginal content without hiding the whole page footer zone."""
    page_by_number = {page.number: _metric_page(page) for page in pages}
    marginal = classify_marginal_spans(spans, pages)
    excluded: Counter[str] = Counter()
    content: list[TextSpan] = []
    violations: list[MarginViolation] = []
    invalid_bbox_count = 0

    for index, span in enumerate(spans):
        chars = significant_character_count(span.text)
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
        if not bbox_within_margins(span.bbox, page):
            violations.append(
                MarginViolation(
                    span=span,
                    page=page,
                    bounds=margin_bounds(page),
                )
            )

    return MarginCheckResult(
        content_spans=tuple(content),
        violations=tuple(violations),
        measured_pages=tuple(sorted({span.page for span in content})),
        invalid_bbox_count=invalid_bbox_count,
        excluded_counts=tuple(sorted(excluded.items())),
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
                    if (
                        bbox is None
                        or bbox.x1 - bbox.x0 <= 2.0
                        or bbox.y1 - bbox.y0 <= 2.0
                    ):
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
) -> LayoutMarginCheckResult:
    """Check image/vector bounds while excluding only repeated marginal objects."""
    page_by_number = {page.number: _metric_page(page) for page in pages}
    repetitions: dict[tuple[str, str, str], list[PdfLayoutObject]] = defaultdict(list)
    marginal: set[PdfLayoutObject] = set()
    required_pages = max(2, math.ceil(len(pages) * 0.5))

    for item in objects:
        page = page_by_number.get(item.page)
        if page is None:
            continue
        zone = _bbox_marginal_zone(item.bbox, page, nominal_height=8.0)
        if zone is not None:
            repetitions[(zone, item.kind, item.signature)].append(item)
    for candidates in repetitions.values():
        if len({item.page for item in candidates}) >= required_pages:
            relative_y = [
                item.bbox.y0 / page_by_number[item.page].height for item in candidates
            ]
            if max(relative_y) - min(relative_y) <= 0.025:
                marginal.update(candidates)

    excluded: Counter[str] = Counter()
    violations: list[LayoutMarginViolation] = []
    for item in objects:
        if item in marginal:
            excluded[f"repeated_{item.kind}_marginalia"] += 1
            continue
        page = page_by_number.get(item.page)
        if page is not None and not bbox_within_margins(item.bbox, page):
            violations.append(
                LayoutMarginViolation(
                    item=item,
                    page=page,
                    bounds=margin_bounds(page),
                )
            )
    return LayoutMarginCheckResult(
        violations=tuple(violations),
        excluded_counts=tuple(sorted(excluded.items())),
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
        deltas = [
            baselines[index + 1] - baselines[index] for index in range(len(baselines) - 1)
        ]
        positive = [delta for delta in deltas if delta > 0]
        if not positive:
            continue
        ratios.append(statistics.median(positive) / body_size)
    if not ratios:
        return None
    return statistics.median(ratios)
