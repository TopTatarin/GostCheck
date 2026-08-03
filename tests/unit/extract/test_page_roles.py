"""Regression coverage for conservative service-page scoping."""

from __future__ import annotations

from normocontrol.extract.base import BoundingBox, PageInfo, Section, SectionKind, TextSpan
from normocontrol.extract.page_roles import (
    DocumentKind,
    PageRole,
    RoleConfidence,
    analyze_page_roles,
)


def _page(number: int) -> PageInfo:
    return PageInfo(number=number, width=595.0, height=842.0, rotation=0)


def _span(
    page: int,
    text: str,
    *,
    y0: float = 100.0,
    bold: bool = False,
    font_size: float = 14.0,
) -> TextSpan:
    return TextSpan(
        text=text,
        page=page,
        char_start=0,
        char_end=len(text),
        font="Times-Bold" if bold else "Times-Roman",
        font_size=font_size,
        flags=16 if bold else 0,
        bbox=BoundingBox(x0=80.0, y0=y0, x1=510.0, y1=y0 + 14.0),
    )


def _introduction_section(page: int) -> Section:
    return Section(
        section_id="introduction",
        title="Введение",
        kind=SectionKind.INTRODUCTION,
        level=1,
        char_start=0,
        char_end=0,
        page_start=page,
        page_end=page,
        locator="section:introduction",
    )


def test_real_front_matter_sequence_keeps_abstract_and_contents_and_starts_at_intro() -> None:
    analysis = analyze_page_roles(
        (
            _span(
                1,
                "УНИВЕРСИТЕТ ВЫПУСКНАЯ КВАЛИФИКАЦИОННАЯ РАБОТА БАКАЛАВРА НАПРАВЛЕНИЕ ПОДГОТОВКИ",
            ),
            _span(2, "УТВЕРЖДАЮ Министерство Университет студент Исходные данные"),
            _span(3, "Тема задания", y0=470.0),
            _span(
                3,
                "Студент Исходные данные Срок выполнения Руководитель",
                y0=520.0,
            ),
            _span(4, "АННОТАЦИЯ", bold=True),
            _span(4, "В работе рассматривается задание для ВКР.", y0=150.0),
            _span(6, "СОДЕРЖАНИЕ", bold=True),
            _span(6, "Введение 8", y0=180.0),
            _span(9, "ВВЕДЕНИЕ", bold=True),
            _span(9, "Основной текст работы", y0=160.0),
        ),
        tuple(_page(number) for number in range(1, 10)),
        sections=(_introduction_section(9),),
    )

    assert analysis.document_kind is DocumentKind.THESIS
    assert analysis.main_start_page == 9
    assert analysis.excluded_service_pages == frozenset({1, 2, 3})
    assert analysis.pages[3].role is PageRole.ABSTRACT
    assert analysis.pages[5].role is PageRole.CONTENTS
    assert analysis.pages[6].role is PageRole.UNKNOWN
    assert analysis.pages[7].role is PageRole.UNKNOWN
    assert analysis.pages[8].role is PageRole.MAIN_TEXT
    assert "main_start_page=9" in analysis.evidence_summary()
    assert "service_pages=1-3" in analysis.evidence_summary()


def test_introduction_fallback_requires_heading_and_rejects_contents_entry() -> None:
    analysis = analyze_page_roles(
        (
            _span(6, "СОДЕРЖАНИЕ", bold=True),
            _span(6, "Введение 8", y0=180.0),
            _span(9, "ВВЕДЕНИЕ", bold=True),
        ),
        tuple(_page(number) for number in range(1, 10)),
    )

    assert analysis.main_start_page == 9
    assert analysis.pages[5].role is PageRole.CONTENTS
    assert analysis.pages[8].role is PageRole.MAIN_TEXT


def test_lone_assignment_word_or_thesis_phrase_after_introduction_is_not_excluded() -> None:
    analysis = analyze_page_roles(
        (
            _span(1, "Введение", bold=True),
            _span(
                2,
                "В тексте рассматривается задание и выпускная квалификационная работа.",
            ),
        ),
        (_page(1), _page(2)),
    )

    assert analysis.excluded_service_pages == frozenset()
    assert analysis.pages[1].role is PageRole.MAIN_TEXT


def test_assignment_heading_needs_two_template_support_signals() -> None:
    analysis = analyze_page_roles(
        (
            _span(1, "ЗАДАНИЕ", bold=True),
            _span(1, "Студент Исходные данные", y0=160.0),
            _span(2, "Задание", bold=True),
            _span(2, "Обычный учебный текст", y0=160.0),
        ),
        (_page(1), _page(2)),
    )

    assert analysis.excluded_service_pages == frozenset({1})
    assert analysis.pages[1].role is PageRole.UNKNOWN


def test_assignment_mention_without_heading_needs_three_template_support_signals() -> None:
    analysis = analyze_page_roles(
        (
            _span(1, "Тема задания", y0=470.0),
            _span(1, "Студент Исходные данные Руководитель", y0=520.0),
            _span(2, "Тема задания", y0=470.0),
            _span(2, "Студент Исходные данные", y0=520.0),
        ),
        (_page(1), _page(2)),
    )

    assert analysis.excluded_service_pages == frozenset({1})
    assert analysis.pages[1].role is PageRole.UNKNOWN


def test_approval_requires_institution_and_form_context() -> None:
    analysis = analyze_page_roles(
        (
            _span(1, "УТВЕРЖДАЮ Министерство Университет Студент Исходные данные"),
            _span(2, "Утверждаю обычное решение в тексте"),
        ),
        (_page(1), _page(2)),
    )

    assert analysis.excluded_service_pages == frozenset({1})
    assert analysis.pages[1].role is PageRole.UNKNOWN


def test_review_after_main_requires_heading_and_extra_form_signals() -> None:
    analysis = analyze_page_roles(
        (
            _span(1, "Introduction", bold=True),
            _span(2, "В обычном тексте есть отзыв руководителя."),
            _span(3, "ОТЗЫВ", bold=True),
            _span(3, "Руководитель Студент Подпись", y0=160.0),
        ),
        (_page(1), _page(2), _page(3)),
    )

    assert analysis.excluded_service_pages == frozenset({3})
    assert analysis.pages[1].role is PageRole.MAIN_TEXT
    assert analysis.pages[2].role is PageRole.REVIEW


def test_non_service_heading_roles_are_low_confidence_and_retained() -> None:
    analysis = analyze_page_roles(
        (
            _span(1, "БИБЛИОГРАФИЯ", bold=True),
            _span(2, "ПРИЛОЖЕНИЕ", bold=True),
        ),
        (_page(1), _page(2)),
    )

    assert [assessment.role for assessment in analysis.pages] == [
        PageRole.BIBLIOGRAPHY,
        PageRole.APPENDIX,
    ]
    assert all(assessment.confidence is RoleConfidence.LOW for assessment in analysis.pages)
    assert analysis.excluded_service_pages == frozenset()
