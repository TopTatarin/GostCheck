from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from normocontrol.domain import FindingStatus, Severity
from normocontrol.extract.base import (
    DocumentBundle,
    ExtractionQuality,
    PageInfo,
    Section,
    SectionKind,
    SourceFile,
    SourceFormat,
    make_locator,
    sha256_text,
)
from normocontrol.extract.latex import LatexExtractor
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.annotation import Ann03DeclaredCountsRule
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry

from .helpers import default_config, effective_rule, minimal_rubric


def _pdf_bundle(page_count: int) -> DocumentBundle:
    text = "Synthetic compiled PDF."
    source_hash = sha256_text(text)
    section = Section(
        section_id="document",
        title="Документ",
        kind=SectionKind.DOCUMENT,
        level=0,
        char_start=0,
        char_end=len(text),
        locator=make_locator(source_hash, 0, len(text)),
        page_start=1,
        page_end=page_count,
    )
    return DocumentBundle(
        source_format=SourceFormat.PDF,
        source_hash=source_hash,
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="main.pdf", sha256="b" * 64),),
        pages=tuple(
            PageInfo(number=number, width=595.0, height=842.0, rotation=0)
            for number in range(1, page_count + 1)
        ),
        sections=(section,),
        chunks=(),
    )


def _write_project(
    root: Path,
    *,
    annotation: str | None,
    figures: int = 0,
    tables: int = 0,
    appendices: int = 0,
    extra_body: str = "",
    annotation_title: str = "Аннотация",
) -> Path:
    annotation_section = (
        f"\\section{{{annotation_title}}}\n{annotation}\n" if annotation is not None else ""
    )
    figure_blocks = "\n".join(
        "\\begin{figure}\\caption{Synthetic}\\end{figure}" for _ in range(figures)
    )
    table_blocks = "\n".join(
        "\\begin{table}\\caption{Synthetic}\\end{table}" for _ in range(tables)
    )
    appendix_blocks = ""
    if appendices:
        appendix_blocks = "\\appendix\n" + "\n".join(
            f"\\section{{Приложение {chr(1040 + index)}}}\nSynthetic appendix."
            for index in range(appendices)
        )
    main = root / "main.tex"
    main.write_text(
        (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            f"{annotation_section}"
            "\\section{Основной раздел}\n"
            f"{figure_blocks}\n{table_blocks}\n{extra_body}\n"
            f"{appendix_blocks}\n"
            "\\end{document}\n"
        ),
        encoding="utf-8",
    )
    return main


def _run(
    tmp_path: Path,
    *,
    annotation: str | None,
    pages: int = 8,
    figures: int = 2,
    tables: int = 1,
    appendices: int = 1,
    extra_body: str = "",
    include_pdf: bool = True,
    severity: RubricSeverity = RubricSeverity.WARN,
    annotation_title: str = "Аннотация",
):
    main = _write_project(
        tmp_path,
        annotation=annotation,
        figures=figures,
        tables=tables,
        appendices=appendices,
        extra_body=extra_body,
        annotation_title=annotation_title,
    )
    bundle = LatexExtractor(tmp_path).extract(main)
    rule = effective_rule("ANN-03", severity=severity)
    context = ExecutionContext(
        rubric=minimal_rubric(rule),
        config=default_config(),
        bundle=bundle,
        latex=LatexProject(root=tmp_path, main_tex=main),
        pdf_path=None,
        bib_paths=(),
        pdf_bundle=_pdf_bundle(pages) if include_pdf else None,
    )
    return FormalEngine(default_formal_registry()).run(context).findings[0]


def _declaration(
    *,
    pages: int = 8,
    figures: int = 2,
    tables: int = 1,
    appendices: int = 1,
) -> str:
    return (
        f"Работа содержит {pages} страниц, {figures} рисунков, "
        f"{tables} таблиц и {appendices} приложений."
    )


def test_matching_declared_and_actual_counts_pass(tmp_path: Path) -> None:
    finding = _run(tmp_path, annotation=_declaration())

    assert finding.status is FindingStatus.PASS
    assert finding.severity is Severity.WARN
    assert finding.evidence
    assert finding.path is None


@pytest.mark.parametrize(
    ("claim", "expected_fragment"),
    [
        (_declaration(pages=9), "страниц: заявлено 9, факт 8"),
        (_declaration(figures=3), "рисунков: заявлено 3, факт 2"),
        (_declaration(tables=2), "таблиц: заявлено 2, факт 1"),
        (_declaration(appendices=2), "приложений: заявлено 2, факт 1"),
    ],
)
def test_each_count_mismatch_is_reported(
    tmp_path: Path,
    claim: str,
    expected_fragment: str,
) -> None:
    finding = _run(tmp_path, annotation=claim)

    assert finding.status is FindingStatus.FAIL
    assert expected_fragment in finding.message


@pytest.mark.parametrize(
    "annotation",
    [
        "Работа содержит 8 страниц, 2 рисунка и 1 таблицу.",
        "Работа содержит 8 страниц, 2 рисунка и 1 приложение.",
        "Работа содержит 8 страниц, 1 таблицу и 1 приложение.",
        "Работа содержит 2 рисунка, 1 таблицу и 1 приложение.",
    ],
)
def test_partial_declaration_is_unverifiable_not_pass(
    tmp_path: Path,
    annotation: str,
) -> None:
    finding = _run(tmp_path, annotation=annotation)

    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "не найдены все четыре" in finding.message


def test_missing_annotation_is_unverifiable(tmp_path: Path) -> None:
    finding = _run(tmp_path, annotation=None)

    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "Аннотация" in finding.message


def test_conflicting_duplicate_declaration_is_unverifiable(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        annotation=f"{_declaration()} Исправлено: 9 страниц.",
    )

    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "противоречивые" in finding.message


def test_commented_claim_does_not_create_a_conflict(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        annotation=f"{_declaration()}\n% Исправлено: 9 страниц.",
    )

    assert finding.status is FindingStatus.PASS


def test_nfd_alternative_annotation_heading_is_supported(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        annotation=_declaration(),
        annotation_title=unicodedata.normalize("NFD", "Реферат"),
    )

    assert finding.status is FindingStatus.PASS


def test_comments_and_literal_blocks_do_not_inflate_float_counts(tmp_path: Path) -> None:
    fake_floats = (
        "% \\begin{figure}\\caption{Comment}\\end{figure}\n"
        "\\begin{verbatim}\n"
        "\\begin{table}\\caption{Literal}\\end{table}\n"
        "\\end{verbatim}\n"
    )
    finding = _run(
        tmp_path,
        annotation=_declaration(figures=0, tables=0),
        figures=0,
        tables=0,
        extra_body=fake_floats,
    )

    assert finding.status is FindingStatus.PASS


def test_missing_compiled_pdf_is_unverifiable(tmp_path: Path) -> None:
    finding = _run(tmp_path, annotation=_declaration(), include_pdf=False)

    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "required source unavailable: pdf" in finding.message


def test_final_severity_is_preserved(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        annotation=_declaration(pages=9),
        severity=RubricSeverity.ERROR,
    )

    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.ERROR


def test_default_registry_contains_ann_03() -> None:
    registration = default_formal_registry().get(Ann03DeclaredCountsRule.rule_id)

    assert registration is not None
