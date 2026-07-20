from __future__ import annotations

from normocontrol.extract.base import (
    ExtractedDocument,
    ExtractionQuality,
    HeadingCandidate,
    SourceFile,
    SourceFormat,
    sha256_text,
)
from normocontrol.extract.chunking import Chunker, estimate_tokens
from normocontrol.extract.sections import SectionDetector


def document(text: str) -> ExtractedDocument:
    return ExtractedDocument(
        source_format=SourceFormat.LATEX,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="main.tex", sha256="0" * 64),),
        headings=(HeadingCandidate(title="Введение", level=1, char_start=0, origin="latex_ast"),),
    )


def test_long_paragraph_never_exceeds_budget_and_reconstructs_losslessly() -> None:
    text = "Введение\n" + ("Очень длинный синтетический абзац без утраты символов. " * 80)
    extracted = document(text)
    sections = SectionDetector().detect(extracted)
    chunks = Chunker(token_budget=35).chunk(extracted, sections)

    assert len(chunks) > 2
    assert all(chunk.token_count <= 35 for chunk in chunks)
    restored = "".join(chunk.text[chunk.overlap_chars :] for chunk in chunks)
    assert restored == text
    assert all(estimate_tokens(chunk.text[: chunk.overlap_chars]) <= 3 for chunk in chunks)


def test_very_long_word_and_table_without_spaces_are_split() -> None:
    text = "Введение\n" + "сверхдлинноеслово" * 80 + "\n" + "|ячейка|" * 100
    extracted = document(text)
    chunks = Chunker(token_budget=12).chunk(extracted, SectionDetector().detect(extracted))

    assert all(chunk.token_count <= 12 for chunk in chunks)
    assert "".join(chunk.text[chunk.overlap_chars :] for chunk in chunks) == text


def test_quote_resolver_is_hash_bound_and_disclosure_limited() -> None:
    text = "Введение\nКороткое доказательство."
    extracted = document(text)
    sections = SectionDetector().detect(extracted)
    chunks = Chunker(token_budget=100).chunk(extracted, sections)
    from normocontrol.extract.base import DocumentBundle

    bundle = DocumentBundle(
        source_format=extracted.source_format,
        source_hash=extracted.source_hash,
        text=text,
        extraction_quality=extracted.extraction_quality,
        source_files=extracted.source_files,
        sections=sections,
        chunks=chunks,
    )
    quote = chunks[0].resolve_quote(0, 8, max_chars=8)

    assert bundle.resolve_quote(quote.locator, max_chars=8).text == "Введение"
    assert text not in repr(bundle)
    assert text not in repr(chunks[0])
    try:
        bundle.resolve_quote(chunks[0].quote_locator, max_chars=1)
    except ValueError as error:
        assert "disclosure" in str(error)
    else:
        raise AssertionError("oversized quote was unexpectedly disclosed")
