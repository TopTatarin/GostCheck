from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from normocontrol.domain import FindingStatus
from normocontrol.extract.latex import LatexExtractor
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry
from normocontrol.rules.section_floats import (
    Arc01FigurePresenceRule,
    Res01FloatPresenceRule,
    Ssa01FigurePresenceRule,
)

from .helpers import default_config, effective_rule, minimal_rubric

RULE_TITLES = {
    "SSA-01": "Структурный системный анализ",
    "ARC-01": "Архитектурно-техническое решение",
    "RES-01": "Анализ результатов",
}
RULE_MARKUP = {
    "SSA-01": "\\begin{figure}\\caption{As is}\\end{figure}",
    "ARC-01": "\\begin{figure}\\caption{To be}\\end{figure}",
    "RES-01": "\\begin{table}\\caption{Metrics}\\end{table}",
}


def _run(
    tmp_path: Path,
    rule_id: str,
    *,
    sections: tuple[tuple[str, str], ...],
):
    section_source = "\n".join(f"\\section{{{title}}}\n{body}" for title, body in sections)
    main = tmp_path / "main.tex"
    main.write_text(
        (f"\\documentclass{{article}}\n\\begin{{document}}\n{section_source}\n\\end{{document}}\n"),
        encoding="utf-8",
    )
    rule = effective_rule(rule_id, severity=RubricSeverity.WARN)
    context = ExecutionContext(
        rubric=minimal_rubric(rule),
        config=default_config(),
        bundle=LatexExtractor(tmp_path).extract(main),
        latex=LatexProject(root=tmp_path, main_tex=main),
        pdf_path=None,
        bib_paths=(),
    )
    return FormalEngine(default_formal_registry()).run(context).findings[0]


@pytest.mark.parametrize("rule_id", tuple(RULE_TITLES))
def test_target_section_with_required_float_passes(
    tmp_path: Path,
    rule_id: str,
) -> None:
    finding = _run(
        tmp_path,
        rule_id,
        sections=((RULE_TITLES[rule_id], RULE_MARKUP[rule_id]),),
    )

    assert finding.status is FindingStatus.PASS
    assert finding.evidence


@pytest.mark.parametrize("rule_id", tuple(RULE_TITLES))
def test_float_in_another_section_does_not_satisfy_rule(
    tmp_path: Path,
    rule_id: str,
) -> None:
    finding = _run(
        tmp_path,
        rule_id,
        sections=(
            ("Обзор", RULE_MARKUP[rule_id]),
            (RULE_TITLES[rule_id], "Текст без структурного объекта."),
        ),
    )

    assert finding.status is FindingStatus.WARN


@pytest.mark.parametrize("rule_id", tuple(RULE_TITLES))
def test_missing_target_section_is_unverifiable(tmp_path: Path, rule_id: str) -> None:
    finding = _run(
        tmp_path,
        rule_id,
        sections=(("Обзор", RULE_MARKUP[rule_id]),),
    )

    assert finding.status is FindingStatus.UNVERIFIABLE


@pytest.mark.parametrize("rule_id", tuple(RULE_TITLES))
def test_comments_and_literal_blocks_do_not_create_float(
    tmp_path: Path,
    rule_id: str,
) -> None:
    fake = (
        f"% {RULE_MARKUP[rule_id]}\n\\begin{{verbatim}}\n{RULE_MARKUP[rule_id]}\n\\end{{verbatim}}"
    )
    finding = _run(
        tmp_path,
        rule_id,
        sections=((RULE_TITLES[rule_id], fake),),
    )

    assert finding.status is FindingStatus.WARN


@pytest.mark.parametrize(
    ("rule_id", "alternative"),
    [
        ("SSA-01", "Модель as is"),
        ("ARC-01", "Модель to be"),
        ("RES-01", "Экспериментальные результаты"),
    ],
)
def test_nfd_alternative_heading_is_supported(
    tmp_path: Path,
    rule_id: str,
    alternative: str,
) -> None:
    finding = _run(
        tmp_path,
        rule_id,
        sections=(
            (
                unicodedata.normalize("NFD", alternative),
                RULE_MARKUP[rule_id],
            ),
        ),
    )

    assert finding.status is FindingStatus.PASS


def test_res01_accepts_figure_as_well_as_table(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        "RES-01",
        sections=(
            (
                RULE_TITLES["RES-01"],
                "\\begin{figure}\\caption{Metrics}\\end{figure}",
            ),
        ),
    )

    assert finding.status is FindingStatus.PASS


def test_second_matching_section_can_supply_evidence(tmp_path: Path) -> None:
    finding = _run(
        tmp_path,
        "SSA-01",
        sections=(
            ("Системный анализ", "Текст без рисунка."),
            ("Модель as is", RULE_MARKUP["SSA-01"]),
        ),
    )

    assert finding.status is FindingStatus.PASS
    assert finding.evidence


def test_default_registry_contains_section_float_rules() -> None:
    registry = default_formal_registry()

    assert registry.get(Ssa01FigurePresenceRule.rule_id) is not None
    assert registry.get(Arc01FigurePresenceRule.rule_id) is not None
    assert registry.get(Res01FloatPresenceRule.rule_id) is not None
