"""Run formal engine against catalog fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from normocontrol.domain import Finding, FindingStatus
from normocontrol.evaluation.catalog import (
    FixtureCatalog,
    FixtureSpec,
    load_fixture_catalog,
    resolve_fixture_paths,
)
from normocontrol.evaluation.metrics import MetricReport, compute_metrics
from normocontrol.extract.latex import LatexExtractor
from normocontrol.extract.pdf import PdfExtractor
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus


@dataclass(frozen=True, slots=True)
class SuccessBuildService(LatexBuildService):
    """Mock successful LaTeX build for fixture evaluation."""

    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root, main_tex
        return LatexBuildResult(
            status=LatexBuildStatus.SUCCESS,
            returncode=0,
            log_excerpt="mock build success",
        )


def _statuses(findings: tuple[Finding, ...], rule_id: str) -> tuple[FindingStatus, ...]:
    return tuple(finding.status for finding in findings if finding.rule_id == rule_id)


def run_fixture(
    spec: FixtureSpec,
    *,
    repo_root: Path,
    rubric_path: Path,
    config_path: Path,
    build_service: LatexBuildService | None = None,
) -> tuple[Finding, ...]:
    """Execute the formal engine for one catalog fixture."""
    latex_root, pdf_path, bib_paths = resolve_fixture_paths(spec, repo_root=repo_root)
    if latex_root is None and pdf_path is None:
        msg = f"fixture {spec.id} requires latex or pdf path"
        raise ValueError(msg)

    config = load_config(config_path)
    rubric = expand_rubric(load_rubric(rubric_path), config)
    latex = None
    bundle = None
    if pdf_path is not None:
        bundle = PdfExtractor(pdf_path.parent).extract(pdf_path)
    if latex_root is not None:
        main_tex = latex_root / "main.tex"
        latex = LatexProject(root=latex_root, main_tex=main_tex)
        if bundle is None:
            bundle = LatexExtractor(latex_root).extract(main_tex)
    context = ExecutionContext(
        rubric=rubric,
        config=config,
        bundle=bundle,
        latex=latex,
        pdf_path=pdf_path.resolve() if pdf_path is not None else None,
        bib_paths=bib_paths,
    )
    registry = default_formal_registry(build_service=build_service or SuccessBuildService())
    return FormalEngine(registry).run(context).findings


def evaluate_catalog(
    catalog: FixtureCatalog,
    *,
    repo_root: Path,
    rubric_path: Path,
    config_path: Path,
    build_service: LatexBuildService | None = None,
) -> MetricReport:
    """Run all catalog fixtures and compute TP/FP/FN metrics."""
    observations: list[tuple[str, str, str, tuple[FindingStatus, ...]]] = []
    for spec in catalog.fixtures:
        findings = run_fixture(
            spec,
            repo_root=repo_root,
            rubric_path=rubric_path,
            config_path=config_path,
            build_service=build_service,
        )
        for rule_id, expected in spec.labels.items():
            statuses = _statuses(findings, rule_id)
            observations.append((spec.id, rule_id, expected, statuses))
    return compute_metrics(tuple(observations))


def evaluate_catalog_file(
    catalog_path: Path,
    *,
    repo_root: Path,
    rubric_path: Path,
    config_path: Path,
) -> MetricReport:
    """Load a catalog file and evaluate it."""
    catalog = load_fixture_catalog(catalog_path)
    return evaluate_catalog(
        catalog,
        repo_root=repo_root,
        rubric_path=rubric_path,
        config_path=config_path,
    )
