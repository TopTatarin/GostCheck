from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from normocontrol.domain import FindingStatus
from normocontrol.extract.latex import LatexExtractor
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.algorithm import Alg01RepresentationRule, Alg03BlockDescriptionRule
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry

from .helpers import default_config, effective_rule, minimal_rubric


def _run(
    tmp_path: Path,
    *,
    title: str | None = "Алгоритм",
    body: str = "Текстовое описание.",
    other_body: str = "",
    rule_ids: tuple[str, ...] = ("ALG-01", "ALG-03"),
):
    algorithm = f"\\section{{{title}}}\n{body}\n" if title is not None else ""
    main = tmp_path / "main.tex"
    main.write_text(
        (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            f"\\section{{Обзор}}\n{other_body}\n"
            f"{algorithm}"
            "\\section{Заключение}\nSynthetic conclusion.\n"
            "\\end{document}\n"
        ),
        encoding="utf-8",
    )
    rules = tuple(effective_rule(rule_id, severity=RubricSeverity.WARN) for rule_id in rule_ids)
    context = ExecutionContext(
        rubric=minimal_rubric(*rules),
        config=default_config(),
        bundle=LatexExtractor(tmp_path).extract(main),
        latex=LatexProject(root=tmp_path, main_tex=main),
        pdf_path=None,
        bib_paths=(),
    )
    return FormalEngine(default_formal_registry()).run(context).findings


@pytest.mark.parametrize(
    "markup",
    [
        "\\begin{figure}\\caption{Блок-схема}\\end{figure}",
        "\\begin{algorithm}Synthetic pseudocode\\end{algorithm}",
        "\\begin{algorithmic}Synthetic pseudocode\\end{algorithmic}",
    ],
)
def test_alg01_accepts_figure_or_algorithm_environment(
    tmp_path: Path,
    markup: str,
) -> None:
    finding = _run(tmp_path, body=markup, rule_ids=("ALG-01",))[0]

    assert finding.status is FindingStatus.PASS
    assert finding.evidence


def test_alg01_missing_representation_warns_not_pass(tmp_path: Path) -> None:
    finding = _run(tmp_path, rule_ids=("ALG-01",))[0]

    assert finding.status is FindingStatus.WARN


def test_alg01_ignores_commented_and_literal_fake_environments(tmp_path: Path) -> None:
    body = (
        "% \\begin{figure}\\end{figure}\n"
        "\\begin{verbatim}\n"
        "\\begin{algorithm}\\end{algorithm}\n"
        "\\end{verbatim}\n"
    )
    finding = _run(tmp_path, body=body, rule_ids=("ALG-01",))[0]

    assert finding.status is FindingStatus.WARN


def test_alg03_requires_exact_block_number_description(tmp_path: Path) -> None:
    positive = _run(
        tmp_path,
        body="Блок 1. Загрузить документ.",
        rule_ids=("ALG-03",),
    )[0]

    assert positive.status is FindingStatus.PASS
    assert positive.evidence


def test_alg03_paraphrase_and_cross_section_match_do_not_satisfy_rule(
    tmp_path: Path,
) -> None:
    finding = _run(
        tmp_path,
        body="Первый блок загружает документ.",
        other_body="Блок 1. Эта строка относится к обзору.",
        rule_ids=("ALG-03",),
    )[0]

    assert finding.status is FindingStatus.WARN


def test_missing_algorithm_section_is_unverifiable(tmp_path: Path) -> None:
    findings = _run(tmp_path, title=None)

    assert [finding.status for finding in findings] == [
        FindingStatus.UNVERIFIABLE,
        FindingStatus.UNVERIFIABLE,
    ]


def test_nfd_alternative_algorithm_heading_is_supported(tmp_path: Path) -> None:
    title = unicodedata.normalize("NFD", "Описание алгоритма")
    findings = _run(
        tmp_path,
        title=title,
        body=(
            "\\begin{algorithm}Synthetic pseudocode\\end{algorithm}\nБлок 1.\nЗагрузить документ."
        ),
    )

    assert [finding.status for finding in findings] == [
        FindingStatus.PASS,
        FindingStatus.PASS,
    ]


def test_algorithm_findings_follow_rubric_order_deterministically(tmp_path: Path) -> None:
    first = _run(
        tmp_path,
        body="Блок 1. Описание без окружения.",
        rule_ids=("ALG-03", "ALG-01"),
    )
    second = _run(
        tmp_path,
        body="Блок 1. Описание без окружения.",
        rule_ids=("ALG-03", "ALG-01"),
    )

    assert first == second
    assert [finding.rule_id for finding in first] == ["ALG-03", "ALG-01"]


def test_default_registry_contains_algorithm_formal_rules() -> None:
    registry = default_formal_registry()

    assert registry.get(Alg01RepresentationRule.rule_id) is not None
    assert registry.get(Alg03BlockDescriptionRule.rule_id) is not None
