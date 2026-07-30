from __future__ import annotations

import unicodedata
from pathlib import Path

from normocontrol.domain import FindingStatus
from normocontrol.extract.latex import LatexExtractor
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry
from normocontrol.rules.task_items import Tsk02TaskItemLengthRule

from .helpers import default_config, effective_rule, minimal_rubric


def _run(
    tmp_path: Path,
    *,
    title: str | None = "Постановка задачи",
    body: str = "",
    other_body: str = "",
):
    task_section = f"\\section{{{title}}}\n{body}\n" if title is not None else ""
    main = tmp_path / "main.tex"
    main.write_text(
        (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            f"\\section{{Обзор}}\n{other_body}\n"
            f"{task_section}"
            "\\end{document}\n"
        ),
        encoding="utf-8",
    )
    rule = effective_rule("TSK-02", severity=RubricSeverity.WARN)
    context = ExecutionContext(
        rubric=minimal_rubric(rule),
        config=default_config(),
        bundle=LatexExtractor(tmp_path).extract(main),
        latex=LatexProject(root=tmp_path, main_tex=main),
        pdf_path=None,
        bib_paths=(),
    )
    return FormalEngine(default_formal_registry()).run(context).findings[0]


def _list(*items: str, environment: str = "enumerate") -> str:
    joined = "\n".join(f"\\item {item}" for item in items)
    return f"\\begin{{{environment}}}\n{joined}\n\\end{{{environment}}}"


def test_all_expanded_task_items_pass(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        body=_list(
            "Формализовать проверяемые требования к структуре документа.",
            "Реализовать детерминированную проверку точных свидетельств.",
        ),
    )

    assert finding.status is FindingStatus.PASS
    assert finding.evidence


def test_partial_list_with_short_item_warns_without_disclosing_text(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        body=_list(
            "Разработать алгоритм.",
            "Проверить воспроизводимость результатов на синтетическом наборе.",
        ),
    )

    assert finding.status is FindingStatus.WARN
    assert "коротких пунктов задач: 1" in finding.message
    assert "Разработать алгоритм" not in finding.message


def test_length_boundary_29_warns_and_30_passes(tmp_path: Path) -> None:
    short = _run(tmp_path, body=_list("а" * 29))
    exact = _run(tmp_path, body=_list("а" * 30))

    assert short.status is FindingStatus.WARN
    assert exact.status is FindingStatus.PASS


def test_itemize_is_supported_and_markup_is_not_counted(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        body=_list(
            "\\textbf{Кратко}.",
            environment="itemize",
        ),
    )

    assert finding.status is FindingStatus.WARN
    assert "минимальная длина 7" in finding.message


def test_list_in_another_section_does_not_satisfy_rule(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        body="Задачи описаны связным текстом.",
        other_body=_list("Очень длинный пункт списка из другого раздела документа."),
    )

    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "список задач не найден" in finding.message


def test_missing_task_section_is_unverifiable(tmp_path: Path) -> None:
    finding = _run(tmp_path, title=None, other_body=_list("Разработать алгоритм."))

    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "раздел" in finding.message


def test_comments_and_literal_items_are_ignored(tmp_path: Path) -> None:
    body = (
        "% \\begin{enumerate}\\item Коротко.\\end{enumerate}\n"
        "\\begin{verbatim}\n"
        "\\begin{enumerate}\\item Коротко.\\end{enumerate}\n"
        "\\end{verbatim}\n" + _list("Подготовить проверяемый синтетический набор для испытаний.")
    )
    finding = _run(tmp_path, body=body)

    assert finding.status is FindingStatus.PASS


def test_nfd_alternative_task_heading_is_supported(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        title=unicodedata.normalize("NFD", "Цель и задачи"),
        body=_list("Разработать проверяемый алгоритм обработки документа."),
    )

    assert finding.status is FindingStatus.PASS


def test_duplicate_lists_are_combined_deterministically(tmp_path: Path) -> None:
    body = (
        _list("Подготовить воспроизводимый набор исходных требований.") + "\n" + _list("Проверить.")
    )

    first = _run(tmp_path, body=body)
    second = _run(tmp_path, body=body)

    assert first == second
    assert first.status is FindingStatus.WARN
    assert "коротких пунктов задач: 1" in first.message


def test_default_registry_contains_tsk_02() -> None:
    registration = default_formal_registry().get(Tsk02TaskItemLengthRule.rule_id)

    assert registration is not None
