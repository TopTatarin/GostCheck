"""Unit tests for D-05 literature review rules."""

from __future__ import annotations

from pathlib import Path

from normocontrol.domain import FindingStatus
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.context import LatexProject
from normocontrol.rules.review import Rev01MinimumSourcesRule, Rev04ForbiddenSourceTypesRule

from .helpers import default_config, effective_rule, execution_context, minimal_rubric


def test_rev01_warns_when_too_few_sources(tmp_path: Path) -> None:
    project, bib_path = _review_project(
        tmp_path,
        body="\\section{Обзор НТИ}\n\\cite{a,b,c}.\n",
        bib=(
            "@article{a, author={A}, title={T}, year={2024}, journaltitle={J}}\n"
            "@article{b, author={B}, title={T}, year={2024}, journaltitle={J}}\n"
            "@article{c, author={C}, title={T}, year={2024}, journaltitle={J}}\n"
        ),
    )
    rule = effective_rule("REV-01", severity=RubricSeverity.WARN)
    context = execution_context(
        minimal_rubric(rule),
        latex=project,
        bib_paths=(bib_path,),
        config=default_config(),
    )
    outcome = Rev01MinimumSourcesRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.WARN


def test_rev04_fails_on_wikipedia_source(tmp_path: Path) -> None:
    project, bib_path = _review_project(
        tmp_path,
        body="\\section{Обзор НТИ}\n\\cite{bad}.\n",
        bib=(
            "@online{bad, author={A}, title={T}, year={2024}, "
            "url={https://wikipedia.org/wiki/Demo}, urldate={2026-01-01}}\n"
        ),
    )
    context = execution_context(
        minimal_rubric(effective_rule("REV-04")),
        latex=project,
        bib_paths=(bib_path,),
    )
    outcome = Rev04ForbiddenSourceTypesRule().run(context, effective_rule("REV-04"))
    assert outcome.findings[0].status is FindingStatus.FAIL


def _review_project(tmp_path: Path, *, body: str, bib: str) -> tuple[LatexProject, Path]:
    root = tmp_path / "project"
    root.mkdir()
    (root / "gostcheck-vkr.cls").write_text(
        "\\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex-gost}\n",
        encoding="utf-8",
    )
    (root / "protected-files.yaml").write_text(
        "version: 1\nclass_files:\n  - path: gostcheck-vkr.cls\n    sha256: "
        + "a" * 64
        + "\nallowed_renewcommand: []\n",
        encoding="utf-8",
    )
    (root / "main.tex").write_text(
        f"\\documentclass{{gostcheck-vkr}}\n\\begin{{document}}\n{body}\\end{{document}}\n",
        encoding="utf-8",
    )
    bib_path = root / "refs.bib"
    bib_path.write_text(bib, encoding="utf-8")
    return LatexProject(root=root, main_tex=root / "main.tex"), bib_path
