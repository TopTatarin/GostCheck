"""Section-aware, lossless and token-bounded document chunking."""

from __future__ import annotations

import math
import re

from normocontrol.extract.base import (
    DocumentChunk,
    ExtractedDocument,
    Section,
    make_locator,
)


def estimate_tokens(text: str) -> int:
    """Conservatively estimate tokenizer-independent UTF-8 token usage."""
    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def _last_boundary(text: str, start: int, hard_end: int) -> int:
    """Prefer paragraph, sentence, then whitespace boundaries without dropping bytes."""
    if hard_end >= len(text):
        return hard_end
    window = text[start:hard_end]
    minimum = max(1, len(window) // 3)
    patterns = (r"\n\s*\n", r"[.!?…][\"'»)]*\s+", r"\s+")
    for pattern in patterns:
        candidates = [match.end() for match in re.finditer(pattern, window)]
        if candidates and candidates[-1] >= minimum:
            return start + candidates[-1]
    return hard_end


def _max_fitting_end(text: str, start: int, end: int, budget: int) -> int:
    low, high = start + 1, end
    best = start
    while low <= high:
        middle = (low + high) // 2
        if estimate_tokens(text[start:middle]) <= budget:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best == start:
        # A single Unicode code point can conservatively exceed a tiny budget.
        return start + 1
    return best


def _overlap_start(
    text: str,
    content_start: int,
    maximum_tokens: int,
    minimum_start: int,
) -> int:
    if content_start == minimum_start or maximum_tokens == 0:
        return content_start
    low, high = minimum_start, content_start
    best = content_start
    while low <= high:
        middle = (low + high) // 2
        tokens = estimate_tokens(text[middle:content_start])
        if tokens <= maximum_tokens:
            best = middle
            high = middle - 1
        else:
            low = middle + 1
    return best


def _page_range(
    document: ExtractedDocument,
    start: int,
    end: int,
    section: Section,
) -> tuple[int | None, int | None]:
    pages = sorted(
        {span.page for span in document.spans if span.char_end > start and span.char_start < end}
    )
    if pages:
        return pages[0], pages[-1]
    return section.page_start, section.page_end


class Chunker:
    """Split by sections and textual boundaries with at most ten percent overlap."""

    def __init__(self, token_budget: int = 800, overlap_ratio: float = 0.1) -> None:
        if token_budget < 1:
            raise ValueError("token_budget must be positive")
        if not 0 <= overlap_ratio <= 0.1:
            raise ValueError("overlap_ratio must be between 0 and 0.1")
        self.token_budget = token_budget
        self.overlap_ratio = overlap_ratio

    def chunk(
        self,
        document: ExtractedDocument,
        sections: tuple[Section, ...],
    ) -> tuple[DocumentChunk, ...]:
        """Create chunks whose unique portions reproduce the source exactly."""
        chunks: list[DocumentChunk] = []
        overlap_tokens = math.floor(self.token_budget * self.overlap_ratio)
        for section in sections:
            content_start = section.char_start
            sequence = 1
            while content_start < section.char_end:
                char_start = _overlap_start(
                    document.text,
                    content_start,
                    overlap_tokens,
                    section.char_start,
                )
                hard_end = _max_fitting_end(
                    document.text,
                    char_start,
                    section.char_end,
                    self.token_budget,
                )
                char_end = _last_boundary(document.text, content_start, hard_end)
                if char_end <= content_start:
                    char_end = hard_end
                payload = document.text[char_start:char_end]
                # Boundary selection can only shorten the fitting slice.
                token_count = estimate_tokens(payload)
                page_start, page_end = _page_range(document, char_start, char_end, section)
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{section.section_id}:{sequence}",
                        text=payload,
                        token_count=token_count,
                        source_hash=document.source_hash,
                        section_id=section.section_id,
                        char_start=char_start,
                        content_start=content_start,
                        char_end=char_end,
                        overlap_chars=content_start - char_start,
                        page_start=page_start,
                        page_end=page_end,
                        quote_locator=make_locator(document.source_hash, char_start, char_end),
                    )
                )
                content_start = char_end
                sequence += 1
        return tuple(chunks)
