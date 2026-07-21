from __future__ import annotations

import unicodedata

from normocontrol.semantic.evidence import EvidenceVerifier
from normocontrol.semantic.schemas import EvidenceQuote

from .helpers import make_bundle


def test_exact_and_normalized_nfd_quotes_are_accepted() -> None:
    chunk = make_bundle().chunks[0]
    quote = unicodedata.normalize("NFD", "СИНТЕТИЧЕСКОЕ доказательство")
    result = EvidenceVerifier().verify(
        (EvidenceQuote(chunk_id=chunk.chunk_id, quote=quote),),
        (chunk,),
    )

    assert result.valid
    assert result.evidence[0].locator == chunk.quote_locator


def test_fabricated_duplicate_and_other_section_evidence_is_rejected() -> None:
    bundle = make_bundle()
    annotation, introduction = bundle.chunks[:2]
    verifier = EvidenceVerifier()

    fabricated = verifier.verify(
        (EvidenceQuote(chunk_id=annotation.chunk_id, quote="выдуманная цитата"),),
        (annotation,),
    )
    duplicate = verifier.verify(
        (
            EvidenceQuote(chunk_id=annotation.chunk_id, quote="Синтетическое доказательство"),
            EvidenceQuote(chunk_id=annotation.chunk_id, quote="синтетическое  доказательство"),
        ),
        (annotation,),
    )
    wrong_section = verifier.verify(
        (EvidenceQuote(chunk_id=introduction.chunk_id, quote="Synthetic evidence"),),
        (annotation,),
    )

    assert fabricated.errors == ("quote_not_found",)
    assert duplicate.errors == ("duplicate_evidence",)
    assert wrong_section.errors == ("chunk_not_allowed",)
