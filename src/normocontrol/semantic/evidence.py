"""Deterministic verification of model-supplied evidence quotes."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from normocontrol.extract.base import DocumentChunk
from normocontrol.semantic.schemas import EvidenceQuote, VerifiedEvidence


def normalize_quote(value: str) -> str:
    """Normalize Unicode, case and whitespace without semantic fuzzy matching."""
    normalized = unicodedata.normalize("NFC", value).casefold().replace("ё", "е")
    normalized = re.sub(r"[\u00ad\u200b-\u200d\ufeff]", "", normalized)
    return " ".join(normalized.split())


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
            if not normalized or normalized not in normalize_quote(chunk.text):
                errors.append("quote_not_found")
                continue
            verified.append(
                VerifiedEvidence(
                    chunk_id=item.chunk_id,
                    quote=item.quote,
                    locator=chunk.quote_locator,
                )
            )
        ordered = tuple(
            sorted(verified, key=lambda item: (item.chunk_id, normalize_quote(item.quote)))
        )
        return EvidenceVerification(evidence=ordered, errors=tuple(sorted(errors)))
