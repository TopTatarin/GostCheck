from __future__ import annotations

from normocontrol.extract.base import (
    ExtractedDocument,
    ExtractionQuality,
    HeadingCandidate,
    SectionKind,
    SourceFile,
    SourceFormat,
    sha256_text,
)
from normocontrol.extract.sections import SectionDetector


def test_old_and_new_section_names_and_lettered_appendix_are_addressable() -> None:
    text = "Аннотация\nA\nВведение\nB\nВыводы\nC\nЗаключение\nD\nПриложение А\nE"
    titles = ("Аннотация", "Введение", "Выводы", "Заключение", "Приложение А")
    headings = tuple(
        HeadingCandidate(title=title, level=1, char_start=text.index(title), origin="latex_ast")
        for title in titles
    )
    document = ExtractedDocument(
        source_format=SourceFormat.LATEX,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="main.tex", sha256="0" * 64),),
        headings=headings,
    )

    sections = SectionDetector().detect(document)

    assert [section.kind for section in sections] == [
        SectionKind.ANNOTATION,
        SectionKind.INTRODUCTION,
        SectionKind.CONCLUSION,
        SectionKind.CONCLUSION,
        SectionKind.APPENDIX,
    ]
    assert [section.section_id for section in sections][-3:] == [
        "conclusion",
        "conclusion-2",
        "appendix-а",
    ]


def test_ast_candidate_wins_over_pdf_fallback_at_same_position() -> None:
    text = "Введение\nТекст"
    document = ExtractedDocument(
        source_format=SourceFormat.LATEX,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="main.tex", sha256="0" * 64),),
        headings=(
            HeadingCandidate(
                title="Неточное введение", level=1, char_start=0, origin="pdf_heading"
            ),
            HeadingCandidate(title="Введение", level=2, char_start=0, origin="latex_ast"),
        ),
    )

    section = SectionDetector().detect(document)[0]

    assert section.title == "Введение"
    assert section.kind is SectionKind.INTRODUCTION
