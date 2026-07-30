"""Integration tests for D-05 bibliography and review rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from normocontrol.domain import FindingStatus
from normocontrol.extract.latex import LatexExtractor
from normocontrol.orchestrator import OrchestratorHooks, run_pipeline
from normocontrol.reporting.json_report import load_report_schema, validate_published_report
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry
from normocontrol.run_context import RunRequest, parse_only
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
    ],
)
def test_bib_and_review_fixtures_run_through_orchestrator(
    tmp_path: Path,
    fixture: str,
    rule_id: str,
    expected_status: FindingStatus,
) -> None:
    report = run_pipeline(
        RunRequest(
            source=FIXTURES / fixture,
            out_dir=tmp_path / "out",
            config_path=CONFIG_PATH,
            rubric_path=RUBRIC_PATH,
            no_llm=True,
            only=parse_only((rule_id,)),
            tool_version="bib-orchestrator-test",
        ),
        OrchestratorHooks(build_service=_SuccessBuildService()),
    )

    formal = next(stage for stage in report.stages if stage.name == "formal")
    assert expected_status in _statuses(formal.findings, rule_id)
    assert all(
        "required source unavailable: bib_files" not in item.message for item in formal.findings
    )


def test_bib02_bib03_unverifiable_without_protected_config() -> None:
    """Missing protected-files.yaml with a clean script must be UNVERIFIABLE, not FAIL."""
    _, findings = _run_fixture("missing_class")
    for rule_id in ("BIB-02", "BIB-03"):
        statuses = _statuses(findings, rule_id)
        assert statuses == (FindingStatus.UNVERIFIABLE,), (rule_id, statuses)
    messages = " ".join(
        finding.message for finding in findings if finding.rule_id in ("BIB-02", "BIB-03")
    )
    assert "класс не задаёт" not in messages
    assert "класс не задаёт ГОСТ-совместимый" not in messages


def test_bib02_bib03_fail_preserved_with_trusted_class_missing_setting() -> None:
    """A trusted class file that genuinely lacks the setting must keep failing."""
    _, findings = _run_fixture("fail_trusted_class")
    assert FindingStatus.FAIL in _statuses(findings, "BIB-02")
    assert FindingStatus.FAIL in _statuses(findings, "BIB-03")


def test_missing_class_report_is_schema_valid(tmp_path: Path) -> None:
    report = run_pipeline(
        RunRequest(
            source=FIXTURES / "missing_class",
            out_dir=tmp_path / "out",
            config_path=CONFIG_PATH,
            rubric_path=RUBRIC_PATH,
            no_llm=True,
            only=parse_only(("BIB-02", "BIB-03")),
            tool_version="bib-missing-class-test",
        ),
        OrchestratorHooks(build_service=_SuccessBuildService()),
    )
    formal = next(stage for stage in report.stages if stage.name == "formal")
    assert FindingStatus.UNVERIFIABLE in _statuses(formal.findings, "BIB-02")
    assert FindingStatus.UNVERIFIABLE in _statuses(formal.findings, "BIB-03")
    published = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    validate_published_report(published, schema=load_report_schema())
