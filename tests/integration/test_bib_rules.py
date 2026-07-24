"""Integration tests for D-05 bibliography and review rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from normocontrol.domain import FindingStatus
from normocontrol.extract.latex import LatexExtractor
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "latex" / "bib"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"
RUBRIC_PATH = ROOT / "rubric.yaml"

D05_RULES = frozenset(
    {
        "BIB-01",
        "BIB-02",
        "BIB-03",
        "BIB-04",
        "BIB-05",
        "REV-01",
        "REV-02",
        "REV-03",
        "REV-04",
        "REV-07",
    }
)


@dataclass(frozen=True, slots=True)
class _SuccessBuildService(LatexBuildService):
    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        del project_root, main_tex
        return LatexBuildResult(
            status=LatexBuildStatus.SUCCESS,
            returncode=0,
            log_excerpt="mock build success",
        )


def _run_fixture(fixture_name: str):
    project_root = FIXTURES / fixture_name
    main_tex = project_root / "main.tex"
    rubric = expand_rubric(load_rubric(RUBRIC_PATH), load_config(CONFIG_PATH))
    bundle = LatexExtractor(project_root).extract(main_tex)
    context = ExecutionContext(
        rubric=rubric,
        config=load_config(CONFIG_PATH),
        bundle=bundle,
        latex=LatexProject(root=project_root, main_tex=main_tex),
        pdf_path=None,
        bib_paths=(project_root / "refs.bib",),
    )
    engine = FormalEngine(default_formal_registry(build_service=_SuccessBuildService()))
    result = engine.run(context)
    findings = tuple(finding for finding in result.findings if finding.rule_id in D05_RULES)
    return result, findings


def _statuses(findings, rule_id: str) -> tuple[FindingStatus, ...]:
    return tuple(finding.status for finding in findings if finding.rule_id == rule_id)


def test_pass_fixture_has_no_blocking_d05_failures() -> None:
    _, findings = _run_fixture("pass")
    blocking = tuple(
        finding
        for finding in findings
        if finding.status is FindingStatus.FAIL and finding.severity.value == "error"
    )
    assert not blocking, [(item.rule_id, item.message) for item in blocking]


@pytest.mark.parametrize(
    ("fixture", "rule_id", "expected_status"),
    [
        ("fail_bib01", "BIB-01", FindingStatus.FAIL),
        ("fail_bib02", "BIB-02", FindingStatus.FAIL),
        ("fail_bib03", "BIB-03", FindingStatus.FAIL),
        ("fail_bib04", "BIB-04", FindingStatus.FAIL),
        ("fail_bib05", "BIB-05", FindingStatus.WARN),
        ("fail_rev01", "REV-01", FindingStatus.WARN),
        ("fail_rev02", "REV-02", FindingStatus.WARN),
        ("fail_rev03", "REV-03", FindingStatus.WARN),
        ("fail_rev04", "REV-04", FindingStatus.FAIL),
        ("fail_rev07", "REV-07", FindingStatus.WARN),
    ],
)
def test_fail_fixtures_trigger_expected_rule(
    fixture: str,
    rule_id: str,
    expected_status: FindingStatus,
) -> None:
    _, findings = _run_fixture(fixture)
    assert expected_status in _statuses(findings, rule_id)
