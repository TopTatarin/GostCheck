"""Deterministic verification of model-supplied evidence quotes."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from normocontrol.extract.base import DocumentChunk
from normocontrol.semantic.schemas import EvidenceQuote, VerifiedEvidence


def normalize_quote(value: str) -> str:
    """Apply canonical Unicode composition without fuzzy textual matching."""
    return unicodedata.normalize("NFC", value)


def _canonical_exact_span(text: str, quote: str) -> tuple[int, int] | None:
    """Locate one continuous canonically equivalent substring.

    Case, punctuation, spacing, visually similar letters and invisible characters remain
    significant.
    Prefix normalization maps an NFC match back to the original source offsets, including
    source text stored in decomposed Unicode form.
    """
    target = normalize_quote(quote)
    if not target:
        return None

    direct_start = text.find(quote)
    if direct_start >= 0:
        return direct_start, direct_start + len(quote)

    normalized_text = normalize_quote(text)
    normalized_start = normalized_text.find(target)
    while normalized_start >= 0:
        normalized_end = normalized_start + len(target)
        boundaries: dict[int, list[int]] = {}
        for index in range(len(text) + 1):
            normalized_length = len(normalize_quote(text[:index]))
            boundaries.setdefault(normalized_length, []).append(index)
        starts = tuple(reversed(boundaries.get(normalized_start, ())))
        ends = tuple(reversed(boundaries.get(normalized_end, ())))
        for start in starts:
            for end in ends:
                if end >= start and normalize_quote(text[start:end]) == target:
                    return start, end
        normalized_start = normalized_text.find(target, normalized_start + 1)
    return None


@dataclass(frozen=True, slots=True)
class EvidenceVerification:
    """Verified items or non-sensitive validation errors."""

    evidence: tuple[VerifiedEvidence, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


class EvidenceVerifier:
    """Accept quotes only when present in the chunks authorized for a rule."""

    def verify(
        self,
        evidence: tuple[EvidenceQuote, ...],
        allowed_chunks: tuple[DocumentChunk, ...],
    ) -> EvidenceVerification:
        by_id = {chunk.chunk_id: chunk for chunk in allowed_chunks}
        verified: list[VerifiedEvidence] = []
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        for item in evidence:
            normalized = normalize_quote(item.quote)
            key = (item.chunk_id, normalized)
            if key in seen:
                errors.append("duplicate_evidence")
                continue
            seen.add(key)
            chunk = by_id.get(item.chunk_id)
            if chunk is None:
                errors.append("chunk_not_allowed")
                continue
            span = _canonical_exact_span(chunk.text, item.quote)
            if span is None:
                errors.append("quote_not_found")
                continue
            resolved = chunk.resolve_quote(*span, max_chars=400)
            verified.append(
                VerifiedEvidence(
                    chunk_id=item.chunk_id,
                    quote=item.quote,
                    locator=resolved.locator,
                )
            )
        ordered = tuple(
            sorted(verified, key=lambda item: (item.chunk_id, normalize_quote(item.quote)))
        )
        return EvidenceVerification(evidence=ordered, errors=tuple(sorted(errors)))
