"""Unit tests for D-05 bibliography rules."""

from __future__ import annotations

from pathlib import Path

from normocontrol.domain import FindingStatus
from normocontrol.rules.bib_parser import parse_bib_text
from normocontrol.rules.bibliography import (
    Bib01IntextReferencesRule,
    Bib02NumericCitationStyleRule,
    Bib03GostBibliographyRule,
    Bib04OnlineUrldateRule,
)
from normocontrol.rules.cite_symbols import cite_keys, manual_bracket_citations
from normocontrol.rules.context import LatexProject

from .helpers import effective_rule, execution_context, minimal_rubric


def test_bib_parser_reads_entries() -> None:
    entries = parse_bib_text(
        "@article{demo,\n  author = {Author},\n  title = {Title},\n  year = {2024},\n}\n"
    )
    assert len(entries) == 1
    assert entries[0].key == "demo"
    assert entries[0].fields["author"] == "Author"


def test_cite_symbols_detect_manual_brackets() -> None:
    assert manual_bracket_citations("Текст [1, 2-3] без cite.") == ("[1, 2-3]",)


SAMPLE_BIB = "@article{demo, author={A}, title={T}, year={2024}}\n"


def test_bib01_fails_on_footcite(tmp_path: Path) -> None:
    project = _project(tmp_path, body="\\footcite{demo}\n")
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    outcome = Bib01IntextReferencesRule().run(context, effective_rule("BIB-01"))
    assert outcome.findings[0].status is FindingStatus.FAIL


def test_bib02_fails_on_manual_bracket_reference(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        body="Обзор [1].\n",
        cls="\\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex-gost}\n",
    )
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    rule = effective_rule("BIB-02", layer="class+script")
    outcome = Bib02NumericCitationStyleRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.FAIL


def test_bib02_unverifiable_when_protected_config_missing(tmp_path: Path) -> None:
    """No protected-files.yaml -> class_ok must be None, not False (regression)."""
    project = _project(tmp_path, body="\\cite{demo}\n", include_protected=False)
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    rule = effective_rule("BIB-02", layer="class+script")
    outcome = Bib02NumericCitationStyleRule().run(context, rule)
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "класс не задаёт" not in finding.message


def test_bib02_untrusted_cls_with_correct_settings_stays_unverifiable(tmp_path: Path) -> None:
    """An unconfigured .cls file must never be treated as a trusted source."""
    project = _project(
        tmp_path,
        body="\\cite{demo}\n",
        cls="\\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex-gost}\n",
        include_protected=False,
    )
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    rule = effective_rule("BIB-02", layer="class+script")
    outcome = Bib02NumericCitationStyleRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE


def test_bib02_untrusted_cls_without_setting_stays_unverifiable(tmp_path: Path) -> None:
    """An untrusted .cls missing the setting must not become a proven FAIL."""
    project = _project(
        tmp_path,
        body="\\cite{demo}\n",
        cls="\\LoadClass{article}\n",
        include_protected=False,
    )
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    rule = effective_rule("BIB-02", layer="class+script")
    outcome = Bib02NumericCitationStyleRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE


def test_bib02_fails_when_trusted_class_missing_setting(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        body="\\cite{demo}\n",
        cls="\\LoadClass{article}\n",
        include_protected=True,
    )
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    rule = effective_rule("BIB-02", layer="class+script")
    outcome = Bib02NumericCitationStyleRule().run(context, rule)
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert finding.message == "класс не задаёт biblatex-gost style=gost-numeric, sorting=none"


def test_bib02_script_fail_preserved_when_class_missing(tmp_path: Path) -> None:
    project = _project(tmp_path, body="Обзор [1].\n", include_protected=False)
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    rule = effective_rule("BIB-02", layer="class+script")
    outcome = Bib02NumericCitationStyleRule().run(context, rule)
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert "[1]" in finding.message


def test_bib02_passes_with_trusted_class_and_clean_script(tmp_path: Path) -> None:
    project = _project(tmp_path, body="\\cite{demo}\n", include_protected=True)
    context = _bib_context(project, tmp_path / "refs.bib", SAMPLE_BIB)
    rule = effective_rule("BIB-02", layer="class+script")
    outcome = Bib02NumericCitationStyleRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.PASS


def test_bib03_unverifiable_when_protected_config_missing(tmp_path: Path) -> None:
    """No protected-files.yaml with valid .bib entries -> UNVERIFIABLE (regression)."""
    project = _project(tmp_path, body="\\cite{demo}\n", include_protected=False)
    bib = "@article{demo, author={A}, title={T}, year={2024}}\n"
    context = _bib_context(project, tmp_path / "refs.bib", bib)
    rule = effective_rule("BIB-03", layer="class+script")
    outcome = Bib03GostBibliographyRule().run(context, rule)
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "класс не задаёт" not in finding.message


def test_bib03_script_fail_preserved_when_class_missing(tmp_path: Path) -> None:
    project = _project(tmp_path, body="\\cite{demo}\n", include_protected=False)
    bib = "@article{demo, author={A}}\n"
    context = _bib_context(project, tmp_path / "refs.bib", bib)
    rule = effective_rule("BIB-03", layer="class+script")
    outcome = Bib03GostBibliographyRule().run(context, rule)
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert "demo" in finding.message


def test_bib03_fails_when_trusted_class_missing_setting(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        body="\\cite{demo}\n",
        cls="\\LoadClass{article}\n",
        include_protected=True,
    )
    bib = "@article{demo, author={A}, title={T}, year={2024}}\n"
    context = _bib_context(project, tmp_path / "refs.bib", bib)
    rule = effective_rule("BIB-03", layer="class+script")
    outcome = Bib03GostBibliographyRule().run(context, rule)
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert finding.message == "класс не задаёт ГОСТ-совместимый biblatex-gost"


def test_bib03_passes_with_trusted_class_and_valid_entries(tmp_path: Path) -> None:
    project = _project(tmp_path, body="\\cite{demo}\n", include_protected=True)
    bib = "@article{demo, author={A}, title={T}, year={2024}}\n"
    context = _bib_context(project, tmp_path / "refs.bib", bib)
    rule = effective_rule("BIB-03", layer="class+script")
    outcome = Bib03GostBibliographyRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.PASS


def test_bib04_requires_urldate_for_online(tmp_path: Path) -> None:
    project = _project(tmp_path, body="\\cite{demo}\n")
    bib = "@article{demo, author={A}, title={T}, year={2024}, url={https://example.org},}\n"
    context = _bib_context(project, tmp_path / "refs.bib", bib)
    outcome = Bib04OnlineUrldateRule().run(context, effective_rule("BIB-04"))
    assert outcome.findings[0].status is FindingStatus.FAIL


def test_cite_keys_collects_multiple_entries() -> None:
    assert cite_keys("\\cite{a,b}\\cite{c}") == frozenset({"a", "b", "c"})


def _project(
    tmp_path: Path,
    *,
    body: str,
    cls: str = "\\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex-gost}\n",
    include_protected: bool = True,
) -> LatexProject:
    root = tmp_path / "project"
    root.mkdir()
    (root / "gostcheck-vkr.cls").write_text(cls, encoding="utf-8")
    if include_protected:
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
    return LatexProject(root=root, main_tex=root / "main.tex")


def _bib_context(project: LatexProject, bib_path: Path, bib_text: str):
    bib_path.write_text(bib_text, encoding="utf-8")
    return execution_context(
        minimal_rubric(effective_rule("BIB-01")),
        latex=project,
        bib_paths=(bib_path,),
    )
