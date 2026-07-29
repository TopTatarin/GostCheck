"""Integration coverage for the blocking PDF-only formal path."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from normocontrol.domain import ExitCode, Finding, FindingStatus, RuleLayer, Severity
from normocontrol.extract.pdf import PdfExtractor
from normocontrol.orchestrator import run_pipeline
from normocontrol.reporting.json_report import load_report_schema, validate_published_report
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rubric.models import WorkProfile
from normocontrol.rules.context import ExecutionContext
from normocontrol.rules.engine import FormalEngine, RunMode, serialize_findings
from normocontrol.rules.gate import formal_exit_code
from normocontrol.rules.register import default_formal_registry
from normocontrol.run_context import RunRequest

ROOT = Path(__file__).resolve().parents[2]
PDF_FIXTURES = ROOT / "tests" / "fixtures" / "pdf"
RUBRIC_PATH = ROOT / "rubric.yaml"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"
FMT_RULE_IDS = ("FMT-01", "FMT-02", "FMT-03", "FMT-04", "FMT-05")


def _context(pdf_path: Path, profile: WorkProfile = WorkProfile.SOFTWARE) -> ExecutionContext:
    config = load_config(CONFIG_PATH).model_copy(update={"work_profile": profile})
    rubric = expand_rubric(load_rubric(RUBRIC_PATH), config)
    bundle = PdfExtractor(pdf_path.parent).extract(pdf_path)
    return ExecutionContext(
        rubric=rubric,
        config=config,
        bundle=bundle,
        latex=None,
        pdf_path=pdf_path.resolve(),
        bib_paths=(),
    )


def _fmt_findings(pdf_path: Path) -> tuple[Finding, ...]:
    result = FormalEngine(default_formal_registry()).run(_context(pdf_path))
    return tuple(item for item in result.findings if item.rule_id in FMT_RULE_IDS)


def _finding(findings: tuple[Finding, ...], rule_id: str) -> Finding:
    return next(item for item in findings if item.rule_id == rule_id)


def _empty_pdf(path: Path) -> Path:
    document = fitz.open()
    document.new_page(width=595, height=842)
    document.save(path)
    document.close()
    return path


def _appendix_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 96), "Appendix A", fontsize=16)
    page.insert_text(
        (72, 132),
        "Repository: https://github.com/example/synthetic-project",
        fontsize=12,
    )
    document.set_toc([[1, "Appendix A", 1]])
    document.save(path)
    document.close()
    return path


def test_fmt_pass_pdf_runs_available_checks_without_latex_requirement() -> None:
    findings = _fmt_findings(PDF_FIXTURES / "fmt_pass.pdf")

    for rule_id in ("FMT-01", "FMT-02", "FMT-03", "FMT-05"):
        assert _finding(findings, rule_id).status is FindingStatus.PASS
    assert _finding(findings, "FMT-01").evidence
    assert _finding(findings, "FMT-05").evidence
    assert _finding(findings, "FMT-04").status is FindingStatus.UNVERIFIABLE
    assert all(
        "required source unavailable: latex_project" not in item.message for item in findings
    )


def test_app_01_detects_repository_url_in_pdf_appendix(tmp_path: Path) -> None:
    pdf_path = _appendix_pdf(tmp_path / "appendix.pdf")
    result = FormalEngine(default_formal_registry()).run(_context(pdf_path))
    finding = _finding(result.findings, "APP-01")

    assert finding.status is FindingStatus.PASS
    assert finding.severity is Severity.INFO
    assert finding.evidence


@pytest.mark.parametrize(
    ("filename", "rule_id"),
    [
        ("fmt_wrong_font.pdf", "FMT-01"),
        ("fmt_non_bold_heading.pdf", "FMT-02"),
        ("fmt_margin_overflow.pdf", "FMT-05"),
    ],
)
def test_pdf_only_failure_blocks_expected_fmt_rule(
    filename: str,
    rule_id: str,
) -> None:
    findings = _fmt_findings(PDF_FIXTURES / filename)
    expected = _finding(findings, rule_id)

    assert expected.status is FindingStatus.FAIL
    assert formal_exit_code(findings) is ExitCode.FORMAL_FAILURE
    if rule_id in {"FMT-01", "FMT-05"}:
        assert expected.path == filename
        assert expected.page == 1
        assert expected.evidence


def test_pdf_without_text_layer_is_blocking_incomplete(tmp_path: Path) -> None:
    pdf_path = _empty_pdf(tmp_path / "no-text-layer.pdf")
    findings = _fmt_findings(pdf_path)

    assert formal_exit_code(findings) is ExitCode.FORMAL_FAILURE
    for rule_id in ("FMT-01", "FMT-02", "FMT-03", "FMT-05"):
        finding = _finding(findings, rule_id)
        assert finding.status is FindingStatus.UNVERIFIABLE
        assert finding.severity is Severity.ERROR
        if rule_id in {"FMT-01", "FMT-05"}:
            assert finding.path == "no-text-layer.pdf"
            assert finding.page == 1
            assert finding.evidence


def test_llm_unverifiable_does_not_change_formal_gate() -> None:
    context = _context(PDF_FIXTURES / "fmt_pass.pdf")
    fmt01 = tuple(rule for rule in context.rubric.rules if rule.id == "FMT-01")
    filtered = context.rubric.model_copy(update={"rules": fmt01})
    formal = FormalEngine(default_formal_registry()).run(
        context.__class__(
            rubric=filtered,
            config=context.config,
            bundle=context.bundle,
            latex=context.latex,
            pdf_path=context.pdf_path,
            bib_paths=context.bib_paths,
        )
    )
    advisory = Finding(
        rule_id="ANN-01",
        layer=RuleLayer.LLM,
        severity=Severity.ERROR,
        status=FindingStatus.UNVERIFIABLE,
        message="synthetic advisory incomplete",
    )

    assert formal.exit_code == int(ExitCode.SUCCESS)
    assert formal_exit_code((*formal.findings, advisory)) is ExitCode.SUCCESS


def test_parallel_and_sequential_pdf_only_reports_match() -> None:
    context = _context(PDF_FIXTURES / "fmt_pass.pdf")
    engine = FormalEngine(default_formal_registry())

    sequential = engine.run(context, mode=RunMode.SEQUENTIAL)
    parallel = engine.run(context, mode=RunMode.PARALLEL)

    assert serialize_findings(sequential.findings) == serialize_findings(parallel.findings)
    assert sequential.gate == parallel.gate
    assert sequential.exit_code == parallel.exit_code


def test_fmt_results_are_profile_stable() -> None:
    by_profile: dict[WorkProfile, tuple[tuple[str, FindingStatus], ...]] = {}
    pdf_path = PDF_FIXTURES / "fmt_pass.pdf"
    for profile in WorkProfile:
        result = FormalEngine(default_formal_registry()).run(_context(pdf_path, profile))
        by_profile[profile] = tuple(
            (item.rule_id, item.status) for item in result.findings if item.rule_id in FMT_RULE_IDS
        )

    assert len(set(by_profile.values())) == 1


def test_pdf_report_validates_and_does_not_serialize_absolute_source_path(
    tmp_path: Path,
) -> None:
    pdf_path = PDF_FIXTURES / "fmt_pass.pdf"
    out_dir = tmp_path / "report"
    report = run_pipeline(
        RunRequest(
            source=pdf_path,
            out_dir=out_dir,
            config_path=CONFIG_PATH,
            rubric_path=RUBRIC_PATH,
            no_llm=True,
        )
    )
    serialized = (out_dir / "report.json").read_text(encoding="utf-8")
    published = json.loads(serialized)

    assert report.exit_code is ExitCode.FORMAL_FAILURE
    assert str(pdf_path.resolve()) not in serialized
    assert "Body line 0 with enough text" not in serialized
    assert published["counts"]["blocking_unverifiable"] > 0
    assert published["counts"]["formal_errors"] == 0
    validate_published_report(published, schema=load_report_schema())
