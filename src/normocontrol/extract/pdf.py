"""Layout-aware PDF extraction implemented with PyMuPDF."""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import fitz  # type: ignore[import-untyped]

from normocontrol.extract.base import (
    BoundingBox,
    DocumentBundle,
    DocumentExtractor,
    ExtractedDocument,
    ExtractionQuality,
    HeadingCandidate,
    PageInfo,
    PdfEncryptedError,
    PdfExtractionError,
    SourceFile,
    SourceFormat,
    TextSpan,
    safe_relative_path,
    sha256_bytes,
    sha256_text,
)
from normocontrol.extract.chunking import Chunker
from normocontrol.extract.sections import SectionDetector

_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})


def _bbox(value: object) -> tuple[float, float, float, float]:
    sequence = cast(list[float] | tuple[float, ...], value)
    if len(sequence) != 4:
        return 0.0, 0.0, 0.0, 0.0
    return tuple(float(item) for item in sequence)  # type: ignore[return-value]


def _ordered_blocks(blocks: list[dict[str, Any]], page_width: float) -> list[dict[str, Any]]:
    text_blocks = [block for block in blocks if block.get("type") == 0]
    narrow = [
        block
        for block in text_blocks
        if (_bbox(block.get("bbox"))[2] - _bbox(block.get("bbox"))[0]) < page_width * 0.65
    ]
    left = [block for block in narrow if sum(_bbox(block.get("bbox"))[::2]) / 2 < page_width / 2]
    right = [block for block in narrow if sum(_bbox(block.get("bbox"))[::2]) / 2 >= page_width / 2]
    if not left or not right:
        return sorted(
            text_blocks,
            key=lambda block: (_bbox(block.get("bbox"))[1], _bbox(block.get("bbox"))[0]),
        )

    columns = {id(block) for block in (*left, *right)}
    full = [block for block in text_blocks if id(block) not in columns]
    column_top = min(_bbox(block.get("bbox"))[1] for block in narrow)
    column_bottom = max(_bbox(block.get("bbox"))[3] for block in narrow)
    top = [block for block in full if _bbox(block.get("bbox"))[3] <= column_top + 2]
    bottom = [block for block in full if _bbox(block.get("bbox"))[1] >= column_bottom - 2]
    middle = [block for block in full if block not in top and block not in bottom]

    def by_y(block: dict[str, Any]) -> tuple[float, float]:
        return _bbox(block.get("bbox"))[1], _bbox(block.get("bbox"))[0]

    return [
        *sorted(top, key=by_y),
        *sorted(left, key=by_y),
        *sorted(middle, key=by_y),
        *sorted(right, key=by_y),
        *sorted(bottom, key=by_y),
    ]


def _normalized_heading(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


class PdfExtractor(DocumentExtractor):
    """Extract text, layout and section hints without OCR or network services."""

    def __init__(self, project_root: Path | None = None, *, token_budget: int = 800) -> None:
        self.project_root = project_root.resolve(strict=True) if project_root is not None else None
        self.chunker = Chunker(token_budget=token_budget)

    def extract(self, source: Path) -> DocumentBundle:
        """Extract a PDF and return degraded quality when no text layer exists."""
        root = self.project_root or source.parent.resolve(strict=True)
        relative_path = safe_relative_path(source, root)
        payload = source.resolve(strict=True).read_bytes()
        try:
            pdf = fitz.open(stream=payload, filetype="pdf")
        except Exception as error:
            raise PdfExtractionError(f"unable to open PDF: {source.name}") from error
        try:
            if pdf.needs_pass:
                raise PdfEncryptedError(f"PDF requires a password: {source.name}")
            document = self._extract_document(pdf, relative_path, payload)
        finally:
            pdf.close()
        sections = SectionDetector().detect(document)
        chunks = self.chunker.chunk(document, sections)
        return DocumentBundle(
            source_format=document.source_format,
            source_hash=document.source_hash,
            text=document.text,
            extraction_quality=document.extraction_quality,
            source_files=document.source_files,
            spans=document.spans,
            pages=document.pages,
            sections=sections,
            chunks=chunks,
            warnings=document.warnings,
        )

    def _extract_document(
        self,
        pdf: Any,
        relative_path: str,
        payload: bytes,
    ) -> ExtractedDocument:
        text_parts: list[str] = []
        spans: list[TextSpan] = []
        pages: list[PageInfo] = []
        font_candidates: list[tuple[str, float, BoundingBox, int, int]] = []
        page_ranges: dict[int, tuple[int, int]] = {}
        warnings: list[str] = []
        zero_bbox = False

        for page_index in range(pdf.page_count):
            page = pdf.load_page(page_index)
            page_number = page_index + 1
            rect = page.rect
            pages.append(
                PageInfo(
                    number=page_number,
                    width=float(rect.width),
                    height=float(rect.height),
                    rotation=int(page.rotation),
                )
            )
            page_start = sum(len(part) for part in text_parts)
            raw = cast(dict[str, Any], page.get_text("dict", sort=False))
            blocks = cast(list[dict[str, Any]], raw.get("blocks", []))
            for block in _ordered_blocks(blocks, float(rect.width)):
                lines = cast(list[dict[str, Any]], block.get("lines", []))
                for line in lines:
                    line_spans = cast(list[dict[str, Any]], line.get("spans", []))
                    for item in line_spans:
                        value = str(item.get("text", "")).translate(_LIGATURES)
                        if not value:
                            continue
                        start = sum(len(part) for part in text_parts)
                        text_parts.append(value)
                        end = start + len(value)
                        raw_bbox = _bbox(item.get("bbox"))
                        bbox = BoundingBox(
                            x0=raw_bbox[0], y0=raw_bbox[1], x1=raw_bbox[2], y1=raw_bbox[3]
                        )
                        if bbox.x0 == bbox.x1 or bbox.y0 == bbox.y1:
                            zero_bbox = True
                        font_size = float(item.get("size", 0.0))
                        flags_raw = item.get("flags")
                        flags = int(flags_raw) if flags_raw is not None else None
                        spans.append(
                            TextSpan(
                                text=value,
                                page=page_number,
                                char_start=start,
                                char_end=end,
                                font=str(item.get("font", "")) or None,
                                font_size=font_size,
                                flags=flags,
                                bbox=bbox,
                            )
                        )
                        if len(value.strip()) >= 2:
                            font_candidates.append(
                                (value.strip(), font_size, bbox, page_number, start)
                            )
                    if line_spans:
                        text_parts.append("\n")
                if lines:
                    text_parts.append("\n")
            page_end = sum(len(part) for part in text_parts)
            page_ranges[page_number] = (page_start, page_end)

        joined_text = "".join(text_parts)
        text = joined_text[: spans[-1].char_end] if spans else ""
        quality = ExtractionQuality.HIGH if text.strip() else ExtractionQuality.DEGRADED
        if quality is ExtractionQuality.DEGRADED:
            warnings.append("PDF_NO_TEXT_LAYER")
        if zero_bbox:
            warnings.append("PDF_ZERO_BBOX")
            quality = ExtractionQuality.DEGRADED
        source_hash = sha256_text(text)
        headings = self._outline_headings(pdf, text, page_ranges)
        if not headings:
            headings = self._font_headings(font_candidates, pages)
        return ExtractedDocument(
            source_format=SourceFormat.PDF,
            source_hash=source_hash,
            text=text,
            extraction_quality=quality,
            source_files=(SourceFile(path=relative_path, sha256=sha256_bytes(payload)),),
            spans=tuple(spans),
            pages=tuple(pages),
            headings=headings,
            warnings=tuple(warnings),
        )

    def _outline_headings(
        self,
        pdf: Any,
        text: str,
        page_ranges: dict[int, tuple[int, int]],
    ) -> tuple[HeadingCandidate, ...]:
        result: list[HeadingCandidate] = []
        try:
            outline = cast(list[list[Any]], pdf.get_toc(simple=True))
        except Exception:
            return ()
        for item in outline:
            if len(item) < 3:
                continue
            level, title, page = int(item[0]), str(item[1]).strip(), int(item[2])
            if not title or page not in page_ranges:
                continue
            start, end = page_ranges[page]
            position = text.casefold().find(title.casefold(), start, end)
            result.append(
                HeadingCandidate(
                    title=title,
                    level=max(1, level),
                    char_start=start if position < 0 else position,
                    page=page,
                    origin="pdf_outline",
                )
            )
        return tuple(result)

    def _font_headings(
        self,
        candidates: list[tuple[str, float, BoundingBox, int, int]],
        pages: list[PageInfo],
    ) -> tuple[HeadingCandidate, ...]:
        positive_sizes = [size for _, size, _, _, _ in candidates if size > 0]
        if not positive_sizes:
            return ()
        body_size = statistics.median(positive_sizes)
        page_heights = {page.number: page.height for page in pages}
        repetitions: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for title, _, bbox, page, _ in candidates:
            normalized = _normalized_heading(title)
            if normalized:
                repetitions[normalized].append((page, bbox.y0 / page_heights[page]))

        result: list[HeadingCandidate] = []
        for title, size, bbox, page, start in candidates:
            if size < body_size * 1.18 or len(title) > 160:
                continue
            normalized = _normalized_heading(title)
            repeated = repetitions[normalized]
            relative_y = bbox.y0 / page_heights[page]
            is_running_header = (
                len({item[0] for item in repeated}) >= 2
                and (relative_y < 0.15 or relative_y > 0.85)
                and max(item[1] for item in repeated) - min(item[1] for item in repeated) < 0.03
            )
            if is_running_header:
                continue
            result.append(
                HeadingCandidate(
                    title=title,
                    level=1,
                    char_start=start,
                    page=page,
                    origin="pdf_heading",
                )
            )
        return tuple(result)
