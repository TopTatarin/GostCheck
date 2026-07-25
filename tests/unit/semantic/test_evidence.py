from __future__ import annotations

import unicodedata

from normocontrol.semantic.evidence import EvidenceVerifier
from normocontrol.semantic.schemas import EvidenceQuote

from .helpers import make_bundle


def test_exact_and_normalized_nfd_quotes_are_accepted() -> None:
    chunk = make_bundle().chunks[0]
    quote = unicodedata.normalize("NFD", "Синтетическое доказательство")
    result = EvidenceVerifier().verify(
        (EvidenceQuote(chunk_id=chunk.chunk_id, quote=quote),),
        (chunk,),
    )

    assert result.valid
    assert result.evidence[0].locator != chunk.quote_locator


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
            EvidenceQuote(chunk_id=annotation.chunk_id, quote="Синтетическое доказательство"),
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


def test_paraphrase_case_spacing_and_yo_changes_are_rejected() -> None:
    bundle = make_bundle(
        (("Аннотация", "Ёмкое точное доказательство описывает результат проверки."),)
    )
    chunk = bundle.chunks[0]
    verifier = EvidenceVerifier()

    for quote in (
        "Точное доказательство кратко описывает результат",
        "ёмкое точное доказательство",
        "Ёмкое  точное доказательство",
        "Емкое точное доказательство",
    ):
        result = verifier.verify((EvidenceQuote(chunk_id=chunk.chunk_id, quote=quote),), (chunk,))
        assert result.errors == ("quote_not_found",)


def test_repeated_source_quote_uses_first_exact_occurrence_deterministically() -> None:
    bundle = make_bundle(
        (
            (
                "Аннотация",
                "Точная цитата подтверждена. Повтор: Точная цитата подтверждена.",
            ),
        )
    )
    chunk = bundle.chunks[0]
    quote = "Точная цитата подтверждена."

    first = EvidenceVerifier().verify(
        (EvidenceQuote(chunk_id=chunk.chunk_id, quote=quote),),
        (chunk,),
    )
    second = EvidenceVerifier().verify(
        (EvidenceQuote(chunk_id=chunk.chunk_id, quote=quote),),
        (chunk,),
    )

    assert first.valid
    assert first == second
    assert (
        first.evidence[0].locator
        == chunk.resolve_quote(
            chunk.text.index(quote),
            chunk.text.index(quote) + len(quote),
        ).locator
    )
