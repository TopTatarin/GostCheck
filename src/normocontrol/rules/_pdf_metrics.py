"""Shared PDF typography and layout metrics for FMT rules."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable

from normocontrol.extract.base import BoundingBox, PageInfo, TextSpan

MM_TO_PT = 72.0 / 25.4
MARGIN_TOLERANCE_MM = 2.0
MARGINS_MM: dict[str, float] = {
    "left": 30.0,
    "right": 10.0,
    "top": 20.0,
    "bottom": 20.0,
}

_TIMES_RE = re.compile(r"times\s*new\s*roman|times-?roman|tnr", re.IGNORECASE)


def is_times_new_roman(font: str | None) -> bool:
    """Return whether a PDF font name looks like Times New Roman."""
    if not font:
        return False
    normalized = re.sub(r"[\s\-_]+", "", font.casefold())
    if normalized.startswith("times"):
        return True
    return _TIMES_RE.search(font) is not None


def span_is_bold(span: TextSpan) -> bool:
    """Detect bold spans from PyMuPDF flags or font name."""
    if span.flags is not None and span.flags & 16:
        return True
    return bool(span.font and "bold" in span.font.casefold())


def body_spans(spans: tuple[TextSpan, ...]) -> tuple[TextSpan, ...]:
    """Keep spans that look like body text rather than tiny artifacts."""
    return tuple(
        span
        for span in spans
        if span.font_size and span.font_size > 0 and len(span.text.strip()) >= 2
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


def font_size_match_ratio(
    spans: Iterable[TextSpan],
    *,
    expected_pt: float,
    tolerance_pt: float = 0.5,
) -> float:
    """Share of spans whose font size is within tolerance of the expected value."""
    items = tuple(spans)
    if not items:
        return 0.0
    matched = sum(
        1
        for span in items
        if span.font_size is not None
        and abs(span.font_size - expected_pt) <= tolerance_pt
    )
    return matched / len(items)


def times_new_roman_ratio(spans: Iterable[TextSpan]) -> float:
    """Share of spans whose font name resembles Times New Roman."""
    items = tuple(spans)
    if not items:
        return 0.0
    matched = sum(1 for span in items if is_times_new_roman(span.font))
    return matched / len(items)


def page_text_bbox(spans: Iterable[TextSpan], page_number: int) -> BoundingBox | None:
    """Union bbox of all spans on one page."""
    page_spans = [span for span in spans if span.page == page_number]
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
