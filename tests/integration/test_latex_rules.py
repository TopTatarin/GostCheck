"""Integration tests for D-02 LaTeX formal rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
import pytest

from normocontrol.domain import ExitCode, FindingStatus
from normocontrol.extract.base import DocumentBundle, PageInfo, Section, SectionKind
from normocontrol.extract.latex import LatexExtractor
from normocontrol.extract.pdf import PdfExtractor
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rubric.models import WorkProfile
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.gate import blocks_merge
from normocontrol.rules.register import default_formal_registry
from normocontrol.tools.chktex import ChktexResult, ChktexRunner
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "latex"
RUBRIC_PATH = ROOT / "rubric.yaml"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"

D02_RULES = frozenset(
    {
        "SYS-01",
        "SYS-02",
        "SYS-03",
        "STR-01",
        "STR-02",
        "STR-03",
        "STR-04",
        "ANN-02",
        "INT-02",
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


class _MissingChktex(ChktexRunner):
    def lint(self, project_root: Path, main_tex: Path) -> ChktexResult:
        del project_root, main_tex
        return ChktexResult(
            available=False,
            returncode=127,
            output="chktex executable not found",
        )


def _effective_rubric(profile: WorkProfile = WorkProfile.SOFTWARE):
    config = load_config(CONFIG_PATH)
    if config.work_profile is not profile:
        config = config.model_copy(update={"work_profile": profile})
    return expand_rubric(load_rubric(RUBRIC_PATH), config)


def _run_fixture(
    fixture_name: str,
    *,
    bundle: DocumentBundle | None = None,
    build_service: LatexBuildService | None = None,
    chktex: ChktexRunner | None = None,
) -> tuple:
    project_root = FIXTURES / fixture_name
    main_tex = project_root / "main.tex"
    if bundle is None:
        bundle = LatexExtractor(project_root).extract(main_tex)
    context = ExecutionContext(
        rubric=_effective_rubric(),
        config=load_config(CONFIG_PATH),
        bundle=bundle,
        latex=LatexProject(root=project_root, main_tex=main_tex),
        pdf_path=None,
        bib_paths=(),
    )
    registry = default_formal_registry(
        build_service=build_service or _SuccessBuildService(),
        chktex=chktex,
    )
    result = FormalEngine(registry).run(context)
    d02_findings = tuple(finding for finding in result.findings if finding.rule_id in D02_RULES)
    return result, d02_findings


def _statuses(findings, rule_id: str) -> tuple[FindingStatus, ...]:
    return tuple(finding.status for finding in findings if finding.rule_id == rule_id)


def test_pass_fixture_has_no_blocking_d02_failures() -> None:
    result, findings = _run_fixture("pass")
    blocking = tuple(
        finding
        for finding in findings
        if finding.status is FindingStatus.FAIL and finding.severity.value == "error"
    )
    assert not blocking, [(item.rule_id, item.message) for item in blocking]
    assert result.exit_code == int(ExitCode.SUCCESS)
    assert not blocks_merge(result.findings)


@pytest.mark.parametrize(
    ("fixture", "rule_id"),
    [
        ("fail_sys01", "SYS-01"),
        ("fail_sys02", "SYS-02"),
        ("fail_str01", "STR-01"),
        ("fail_str02", "STR-02"),
        ("fail_ann02", "ANN-02"),
        ("fail_int02", "INT-02"),
    ],
)
def test_fail_fixtures_trigger_expected_rule(fixture: str, rule_id: str) -> None:
    _, findings = _run_fixture(fixture)
    assert FindingStatus.FAIL in _statuses(findings, rule_id)


def test_str03_warns_on_short_subsection() -> None:
    project_root = FIXTURES / "pass"
    main_tex = project_root / "main.tex"
    base = LatexExtractor(project_root).extract(main_tex)
    subsection = Section(
        section_id="intro-sub",
        title="Подраздел",
        kind=SectionKind.OTHER,
        level=3,
        char_start=0,
        char_end=10,
        locator="fixture:intro-sub",
        page_start=2,
        page_end=2,
    )
    bundle = base.model_copy(
        update={
            "pages": (PageInfo(number=1, width=595.0, height=842.0, rotation=0),),
            "sections": (*base.sections, subsection),
        }
    )
    _, findings = _run_fixture("pass", bundle=bundle)
    assert FindingStatus.WARN in _statuses(findings, "STR-03")


def test_str04_warns_on_volume_outside_range() -> None:
    project_root = FIXTURES / "pass"
    main_tex = project_root / "main.tex"
    base = LatexExtractor(project_root).extract(main_tex)
    patched_sections: list[Section] = []
    for section in base.sections:
        if section.title == "Введение":
            patched_sections.append(section.model_copy(update={"page_start": 1, "page_end": 10}))
        else:
            patched_sections.append(section)
    bundle = base.model_copy(
        update={
            "pages": tuple(
                PageInfo(number=number, width=595.0, height=842.0, rotation=0)
                for number in range(1, 11)
            ),
            "sections": tuple(patched_sections),
        }
    )
    _, findings = _run_fixture("pass", bundle=bundle)
    assert FindingStatus.WARN in _statuses(findings, "STR-04")


def test_ann03_compares_latex_counters_with_extracted_pdf_pages(tmp_path: Path) -> None:
    main_tex = tmp_path / "main.tex"
    main_tex.write_text(
        (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\section{Аннотация}\n"
            "Работа содержит 3 страницы, 1 рисунок, 1 таблицу и 1 приложение.\n"
            "\\section{Основной раздел}\n"
            "\\begin{figure}\\caption{Synthetic}\\end{figure}\n"
            "\\begin{table}\\caption{Synthetic}\\end{table}\n"
            "\\appendix\n"
            "\\section{Приложение А}\n"
            "Synthetic appendix.\n"
            "\\end{document}\n"
        ),
        encoding="utf-8",
    )
    pdf_path = tmp_path / "main.pdf"
    document = fitz.open()
    for _ in range(3):
        document.new_page(width=595, height=842)
    document.save(pdf_path)
    document.close()

    config = load_config(CONFIG_PATH)
    rubric = _effective_rubric().model_copy(
        update={"rules": tuple(rule for rule in _effective_rubric().rules if rule.id == "ANN-03")}
    )
    context = ExecutionContext(
        rubric=rubric,
        config=config,
        bundle=LatexExtractor(tmp_path).extract(main_tex),
        latex=LatexProject(root=tmp_path, main_tex=main_tex),
        pdf_path=pdf_path,
        bib_paths=(),
        pdf_bundle=PdfExtractor(tmp_path).extract(pdf_path),
    )

    finding = FormalEngine(default_formal_registry()).run(context).findings[0]

    assert finding.rule_id == "ANN-03"
    assert finding.status is FindingStatus.PASS
    assert finding.evidence


def test_algorithm_formal_rules_are_scoped_to_algorithm_section(tmp_path: Path) -> None:
    main_tex = tmp_path / "main.tex"
    main_tex.write_text(
        (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\section{Описание алгоритма}\n"
            "\\begin{figure}\\caption{Блок-схема}\\end{figure}\n"
            "Блок 1. Загрузить документ.\n"
            "\\end{document}\n"
        ),
        encoding="utf-8",
    )
    config = load_config(CONFIG_PATH)
    effective = _effective_rubric()
    rubric = effective.model_copy(
        update={"rules": tuple(rule for rule in effective.rules if rule.id in {"ALG-01", "ALG-03"})}
    )
    context = ExecutionContext(
        rubric=rubric,
        config=config,
        bundle=LatexExtractor(tmp_path).extract(main_tex),
        latex=LatexProject(root=tmp_path, main_tex=main_tex),
        pdf_path=None,
        bib_paths=(),
    )

    findings = FormalEngine(default_formal_registry()).run(context).findings

    assert [finding.rule_id for finding in findings] == ["ALG-01", "ALG-03"]
    assert all(finding.status is FindingStatus.PASS for finding in findings)


def test_sys03_unverifiable_when_latexmk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    _, findings = _run_fixture("pass", build_service=LatexBuildService())
    assert FindingStatus.UNVERIFIABLE in _statuses(findings, "SYS-03")


def test_sys03_unverifiable_only_for_chktex_when_latex_build_succeeds() -> None:
    _, findings = _run_fixture("pass", chktex=_MissingChktex())
    sys03 = tuple(finding for finding in findings if finding.rule_id == "SYS-03")

    assert len(sys03) == 1
    assert sys03[0].status is FindingStatus.UNVERIFIABLE
    assert "chktex" in sys03[0].message
