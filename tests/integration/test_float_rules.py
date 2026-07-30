"""Integration tests for D-04 float and formula rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytest

from normocontrol.domain import FindingStatus
from normocontrol.extract.latex import LatexExtractor
from normocontrol.extract.pdf import PdfExtractor
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
FIXTURES = ROOT / "tests" / "fixtures" / "latex" / "floats"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"
RUBRIC_PATH = ROOT / "rubric.yaml"

D04_RULES = frozenset(
    {
        "FIG-01",
        "FIG-02",
        "FIG-03",
        "FIG-04",
        "FIG-05",
        "FIG-06",
        "FIG-07",
        "TAB-01",
        "TAB-02",
        "TAB-03",
        "CAP-01",
        "MTH-01",
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
        bib_paths=(),
    )
    engine = FormalEngine(default_formal_registry(build_service=_SuccessBuildService()))
    result = engine.run(context)
    findings = tuple(finding for finding in result.findings if finding.rule_id in D04_RULES)
    return result, findings


def _statuses(findings, rule_id: str) -> tuple[FindingStatus, ...]:
    return tuple(finding.status for finding in findings if finding.rule_id == rule_id)


def _save_pdf(document: fitz.Document, path: Path) -> Path:
    document.save(path)
    document.close()
    return path


def _cyrillic_font_path() -> Path | None:
    candidates = (
        Path(r"C:/Windows/Fonts/times.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _fig01_pdf(path: Path, *, caption_page: int) -> Path:
    font_path = _cyrillic_font_path()
    if font_path is None:
        pytest.skip("Cyrillic-capable font not found for FIG-01 PDF integration test")

    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_font(fontname="FigCyr", fontfile=str(font_path))
    page.insert_text(
        (100, 120),
        "Система показана на рисунке 1.",
        fontsize=14,
        fontname="FigCyr",
    )
    for number in range(2, caption_page):
        filler = document.new_page(width=595, height=842)
        filler.insert_font(fontname="FigCyr", fontfile=str(font_path))
        filler.insert_text(
            (100, 120),
            f"Промежуточная страница {number}.",
            fontsize=14,
            fontname="FigCyr",
        )
    caption = document.new_page(width=595, height=842)
    caption.insert_font(fontname="FigCyr", fontfile=str(font_path))
    caption.insert_text(
        (100, 120),
        "Рисунок 1 — Схема системы",
        fontsize=14,
        fontname="FigCyr",
    )
    return _save_pdf(document, path)


def _run_fig01_with_pdf(pdf_path: Path, *, latex_fixture: str = "pass"):
    project_root = FIXTURES / latex_fixture
    main_tex = project_root / "main.tex"
    rubric = expand_rubric(load_rubric(RUBRIC_PATH), load_config(CONFIG_PATH))
    bundle = PdfExtractor(pdf_path.parent).extract(pdf_path)
    context = ExecutionContext(
        rubric=rubric,
        config=load_config(CONFIG_PATH),
        bundle=bundle,
        latex=LatexProject(root=project_root, main_tex=main_tex),
        pdf_path=pdf_path.resolve(),
        bib_paths=(),
    )
    engine = FormalEngine(default_formal_registry(build_service=_SuccessBuildService()))
    result = engine.run(context)
    findings = tuple(finding for finding in result.findings if finding.rule_id == "FIG-01")
    return findings


def test_pass_fixture_has_no_blocking_d04_failures() -> None:
    _, findings = _run_fixture("pass")
    blocking = tuple(
        finding
        for finding in findings
        if finding.status is FindingStatus.FAIL and finding.severity.value == "error"
    )
    assert not blocking, [(item.rule_id, item.message) for item in blocking]


@pytest.mark.parametrize(
    ("fixture", "rule_id"),
    [
        ("fail_fig02", "FIG-02"),
        ("fail_fig03", "FIG-03"),
        ("fail_cap01", "CAP-01"),
        ("fail_mth01", "MTH-01"),
    ],
)
def test_fail_fixtures_trigger_expected_rule(fixture: str, rule_id: str) -> None:
    _, findings = _run_fixture(fixture)
    assert FindingStatus.FAIL in _statuses(findings, rule_id)


def test_fig01_passes_when_caption_on_next_pdf_page(tmp_path: Path) -> None:
    pdf_path = _fig01_pdf(tmp_path / "fig01_pass.pdf", caption_page=2)
    findings = _run_fig01_with_pdf(pdf_path)
    assert FindingStatus.PASS in _statuses(findings, "FIG-01")


def test_fig01_warns_when_caption_too_late_in_pdf(tmp_path: Path) -> None:
    pdf_path = _fig01_pdf(tmp_path / "fig01_warn.pdf", caption_page=3)
    findings = _run_fig01_with_pdf(pdf_path)
    assert FindingStatus.WARN in _statuses(findings, "FIG-01")


def test_class_script_rules_unverifiable_without_protected_config() -> None:
    """Missing protected-files.yaml with a clean script must be UNVERIFIABLE, not FAIL."""
    _, findings = _run_fixture("missing_class")
    for rule_id in ("FIG-03", "TAB-02", "MTH-01"):
        statuses = _statuses(findings, rule_id)
        assert statuses == (FindingStatus.UNVERIFIABLE,), (rule_id, statuses)
    messages = " ".join(
        finding.message for finding in findings if finding.rule_id in ("FIG-03", "TAB-02", "MTH-01")
    )
    assert "класс не определяет" not in messages
    assert "класс не задаёт" not in messages
    assert "класс не включает" not in messages


def test_class_script_rules_fail_preserved_with_trusted_class_missing_setting() -> None:
    """A trusted class file that genuinely lacks the setting must keep failing."""
    _, findings = _run_fixture("fail_trusted_class")
    for rule_id in ("FIG-03", "TAB-02", "MTH-01"):
        assert FindingStatus.FAIL in _statuses(findings, rule_id), rule_id


def test_missing_class_float_report_is_schema_valid(tmp_path: Path) -> None:
    report = run_pipeline(
        RunRequest(
            source=FIXTURES / "missing_class",
            out_dir=tmp_path / "out",
            config_path=CONFIG_PATH,
            rubric_path=RUBRIC_PATH,
            no_llm=True,
            only=parse_only(("FIG-03", "TAB-02", "MTH-01")),
            tool_version="float-missing-class-test",
        ),
        OrchestratorHooks(build_service=_SuccessBuildService()),
    )
    formal = next(stage for stage in report.stages if stage.name == "formal")
    for rule_id in ("FIG-03", "TAB-02", "MTH-01"):
        assert FindingStatus.UNVERIFIABLE in _statuses(formal.findings, rule_id)
    published = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    validate_published_report(published, schema=load_report_schema())
