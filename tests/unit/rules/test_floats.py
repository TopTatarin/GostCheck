"""Unit tests for D-04 float and formula rules."""

from __future__ import annotations

from pathlib import Path

from normocontrol.domain import FindingStatus
from normocontrol.extract.base import (
    BoundingBox,
    DocumentBundle,
    ExtractionQuality,
    SourceFile,
    SourceFormat,
    TextSpan,
    sha256_text,
)
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.context import LatexProject
from normocontrol.rules.figures import (
    Fig01PlacementRule,
    Fig02FigureReferenceRule,
    Fig03FigureReferenceStyleRule,
)
from normocontrol.rules.formulas import Mth01NumberedEquationsRule
from normocontrol.rules.latex_source import LatexProjectReader
from normocontrol.rules.latex_symbols import (
    caption_arguments,
    contains_abbreviated_figure_reference,
    contains_unnumbered_display_math,
    figure_blocks,
    reference_targets,
)
from normocontrol.rules.tables import Tab02LongtableContinuationRule

from .helpers import effective_rule, execution_context, minimal_rubric

FIG01_BODY = (
    "\\section{Demo}\n"
    "Система показана на \\ref{fig:demo}.\n"
    "\\begin{figure}\n"
    "\\caption{Рисунок 1 — Схема}\n"
    "\\label{fig:demo}\n"
    "\\end{figure}\n"
)


def _pdf_span(*, text: str, page: int) -> TextSpan:
    return TextSpan(
        text=text,
        page=page,
        char_start=0,
        char_end=len(text),
        font="Times-Roman",
        font_size=14.0,
        flags=None,
        bbox=BoundingBox(x0=100.0, y0=100.0, x1=400.0, y1=114.0),
    )


def _fig01_bundle(*spans: TextSpan) -> DocumentBundle:
    text = " ".join(span.text for span in spans)
    return DocumentBundle(
        source_format=SourceFormat.PDF,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="doc.pdf", sha256="a" * 64),),
        spans=spans,
        sections=(),
        chunks=(),
    )


def _fig01_latex_project(tmp_path: Path) -> LatexProject:
    project = tmp_path / "project"
    project.mkdir()
    (project / "gostcheck-vkr.cls").write_text("\\LoadClass{article}\n", encoding="utf-8")
    (project / "protected-files.yaml").write_text(
        "version: 1\nclass_files:\n  - path: gostcheck-vkr.cls\n    sha256: "
        + "a" * 64
        + "\nallowed_renewcommand: []\n",
        encoding="utf-8",
    )
    (project / "main.tex").write_text(
        f"\\documentclass{{gostcheck-vkr}}\n\\begin{{document}}\n{FIG01_BODY}\\end{{document}}\n",
        encoding="utf-8",
    )
    return LatexProject(root=project, main_tex=project / "main.tex")


def _fig01_context(tmp_path: Path, bundle: DocumentBundle):
    return execution_context(
        minimal_rubric(
            effective_rule("FIG-01", severity=RubricSeverity.WARN),
        ),
        bundle=bundle,
        latex=_fig01_latex_project(tmp_path),
    )


def _class_script_project(
    tmp_path: Path,
    *,
    body: str,
    cls: str,
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


def _class_script_context(project: LatexProject, rule_id: str):
    return execution_context(
        minimal_rubric(effective_rule(rule_id, layer="class+script")),
        latex=project,
    )


SAMPLE = r"""
\begin{figure}
\caption{Рисунок 1 — Demo}
\label{fig:a}
\end{figure}
See \ref{fig:a}.
"""


def test_latex_symbols_extract_figures_and_refs() -> None:
    blocks = figure_blocks(SAMPLE)
    assert len(blocks) == 1
    assert blocks[0].label == "fig:a"
    assert "fig:a" in reference_targets(SAMPLE)


def test_fig01_passes_when_caption_on_next_page(tmp_path: Path) -> None:
    bundle = _fig01_bundle(
        _pdf_span(text="Система показана на рисунке 1.", page=1),
        _pdf_span(text="Рисунок 1 — Схема", page=2),
    )
    context = _fig01_context(tmp_path, bundle)
    rule = effective_rule("FIG-01", severity=RubricSeverity.WARN)
    outcome = Fig01PlacementRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.PASS


def test_fig01_warns_when_caption_too_late(tmp_path: Path) -> None:
    bundle = _fig01_bundle(
        _pdf_span(text="Система показана на рисунке 1.", page=1),
        _pdf_span(text="Рисунок 1 — Схема", page=3),
    )
    context = _fig01_context(tmp_path, bundle)
    rule = effective_rule("FIG-01", severity=RubricSeverity.WARN)
    outcome = Fig01PlacementRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.WARN
    assert "рисунок 1" in outcome.findings[0].message.casefold()


def test_fig01_warns_when_caption_uses_pdf_nonbreaking_spaces(tmp_path: Path) -> None:
    bundle = _fig01_bundle(
        _pdf_span(text="Система показана на рисунке 1.", page=1),
        _pdf_span(text="Рисунок\xa01 — Схема", page=3),
    )
    context = _fig01_context(tmp_path, bundle)
    rule = effective_rule("FIG-01", severity=RubricSeverity.WARN)
    outcome = Fig01PlacementRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.WARN


def test_fig02_fails_without_reference(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}"
        "\\begin{figure}\\caption{R}\\label{f:x}\\end{figure}\\end{document}\n",
        encoding="utf-8",
    )
    context = execution_context(
        minimal_rubric(effective_rule("FIG-02")),
        latex=LatexProject(root=project, main_tex=project / "main.tex"),
    )
    outcome = Fig02FigureReferenceRule().run(context, effective_rule("FIG-02"))
    assert outcome.findings[0].status is FindingStatus.FAIL


def test_fig03_detects_abbreviated_reference() -> None:
    assert contains_abbreviated_figure_reference("см. рис. 2")
    assert contains_abbreviated_figure_reference("см. рис.~2")


_FIG03_CLS_OK = "\\newcommand{\\risref}[1]{рисунке~\\ref{#1}}\n"
_FIG03_CLS_MISSING_MACRO = "\\LoadClass{article}\n"
_FIG03_CLEAN_BODY = "Текст без сокращённых ссылок.\n"
_FIG03_ABBREVIATED_BODY = "см. рис. 2 для деталей.\n"


def test_fig03_unverifiable_when_protected_config_missing(tmp_path: Path) -> None:
    """No protected-files.yaml with a clean script -> UNVERIFIABLE (regression)."""
    project = _class_script_project(
        tmp_path, body=_FIG03_CLEAN_BODY, cls=_FIG03_CLS_OK, include_protected=False
    )
    context = _class_script_context(project, "FIG-03")
    outcome = Fig03FigureReferenceStyleRule().run(
        context, effective_rule("FIG-03", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "не определяет" not in finding.message


def test_fig03_untrusted_cls_without_macro_stays_unverifiable(tmp_path: Path) -> None:
    """An untrusted .cls lacking the macro must not become a proven FAIL."""
    project = _class_script_project(
        tmp_path, body=_FIG03_CLEAN_BODY, cls=_FIG03_CLS_MISSING_MACRO, include_protected=False
    )
    context = _class_script_context(project, "FIG-03")
    outcome = Fig03FigureReferenceStyleRule().run(
        context, effective_rule("FIG-03", layer="class+script")
    )
    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE


def test_fig03_fails_on_abbreviated_reference_even_without_class(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path,
        body=_FIG03_ABBREVIATED_BODY,
        cls=_FIG03_CLS_MISSING_MACRO,
        include_protected=False,
    )
    context = _class_script_context(project, "FIG-03")
    outcome = Fig03FigureReferenceStyleRule().run(
        context, effective_rule("FIG-03", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert finding.message == "обнаружена сокращённая ссылка «рис. N»"


def test_fig03_fails_when_trusted_class_missing_macro(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path, body=_FIG03_CLEAN_BODY, cls=_FIG03_CLS_MISSING_MACRO, include_protected=True
    )
    context = _class_script_context(project, "FIG-03")
    outcome = Fig03FigureReferenceStyleRule().run(
        context, effective_rule("FIG-03", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert finding.message == "класс не определяет макрос \\risref"


def test_fig03_passes_with_trusted_class_and_clean_script(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path, body=_FIG03_CLEAN_BODY, cls=_FIG03_CLS_OK, include_protected=True
    )
    context = _class_script_context(project, "FIG-03")
    outcome = Fig03FigureReferenceStyleRule().run(
        context, effective_rule("FIG-03", layer="class+script")
    )
    assert outcome.findings[0].status is FindingStatus.PASS


def test_cap01_validates_caption_case() -> None:
    captions = caption_arguments("\\caption{Рисунок 1 — Demo}")
    assert captions == ("Рисунок 1 — Demo",)


def test_mth01_detects_display_math() -> None:
    assert contains_unnumbered_display_math("\\[ x = 1 \\]")


def test_mth01_passes_numbered_equation_section(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    cls = (
        "\\RequirePackage{amsmath}\n\\counterwithin{figure}{section}\n"
        "\\captionsetup[figure]{labelsep=endash,position=below,justification=centering}\n"
    )
    (project / "gostcheck-vkr.cls").write_text(cls, encoding="utf-8")
    (project / "protected-files.yaml").write_text(
        "version: 1\nclass_files:\n  - path: gostcheck-vkr.cls\n    sha256: "
        + "a" * 64
        + "\nallowed_renewcommand: []\n",
        encoding="utf-8",
    )
    body = "\\section{Математическая модель}\n\\begin{equation}a=1\\end{equation}\n"
    (project / "main.tex").write_text(
        f"\\documentclass{{gostcheck-vkr}}\n\\begin{{document}}\n{body}\\end{{document}}\n",
        encoding="utf-8",
    )
    context = execution_context(
        minimal_rubric(effective_rule("MTH-01", layer="class+script")),
        latex=LatexProject(root=project, main_tex=project / "main.tex"),
    )
    reader = LatexProjectReader.load(project, project / "main.tex")
    assert reader.section_body("Математическая модель") is not None
    rule = effective_rule("MTH-01", layer="class+script")
    outcome = Mth01NumberedEquationsRule().run(context, rule)
    assert outcome.findings[0].status is FindingStatus.PASS


_MTH01_CLS_OK = "\\RequirePackage{amsmath}\n"
_MTH01_CLS_MISSING_SETTING = "\\LoadClass{article}\n"
_MTH01_NUMBERED_BODY = "\\section{Математическая модель}\n\\begin{equation}a=1\\end{equation}\n"
_MTH01_UNNUMBERED_BODY = "\\section{Математическая модель}\n\\[a=1\\]\n"


def test_mth01_unverifiable_when_protected_config_missing(tmp_path: Path) -> None:
    """No protected-files.yaml with numbered equations -> UNVERIFIABLE (regression)."""
    project = _class_script_project(
        tmp_path, body=_MTH01_NUMBERED_BODY, cls=_MTH01_CLS_OK, include_protected=False
    )
    context = _class_script_context(project, "MTH-01")
    outcome = Mth01NumberedEquationsRule().run(
        context, effective_rule("MTH-01", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "не включает" not in finding.message


def test_mth01_untrusted_cls_without_setting_stays_unverifiable(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path,
        body=_MTH01_NUMBERED_BODY,
        cls=_MTH01_CLS_MISSING_SETTING,
        include_protected=False,
    )
    context = _class_script_context(project, "MTH-01")
    outcome = Mth01NumberedEquationsRule().run(
        context, effective_rule("MTH-01", layer="class+script")
    )
    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE


def test_mth01_script_fail_preserved_when_class_missing(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path,
        body=_MTH01_UNNUMBERED_BODY,
        cls=_MTH01_CLS_MISSING_SETTING,
        include_protected=False,
    )
    context = _class_script_context(project, "MTH-01")
    outcome = Mth01NumberedEquationsRule().run(
        context, effective_rule("MTH-01", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert finding.message == "в разделе обнаружены \\[ \\], $$ или equation*"


def test_mth01_fails_when_trusted_class_missing_setting(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path, body=_MTH01_NUMBERED_BODY, cls=_MTH01_CLS_MISSING_SETTING, include_protected=True
    )
    context = _class_script_context(project, "MTH-01")
    outcome = Mth01NumberedEquationsRule().run(
        context, effective_rule("MTH-01", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert finding.message == "класс не включает amsmath/нумерацию equation"


def test_mth01_passes_with_trusted_class_and_numbered_equations(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path, body=_MTH01_NUMBERED_BODY, cls=_MTH01_CLS_OK, include_protected=True
    )
    context = _class_script_context(project, "MTH-01")
    outcome = Mth01NumberedEquationsRule().run(
        context, effective_rule("MTH-01", layer="class+script")
    )
    assert outcome.findings[0].status is FindingStatus.PASS


_TAB02_CLS_OK = "\\newcommand{\\vkrlongtable}[1]{\\begin{longtable}{#1}\\endfirsthead}\n"
_TAB02_CLS_MISSING_MACRO = "\\LoadClass{article}\n"
_TAB02_CLEAN_BODY = "\\begin{tabular}{ll}\nA & B \\\\\n\\end{tabular}\n"
_TAB02_LONGTABLE_WITHOUT_HEADER = "\\begin{longtable}{ll}\nA & B \\\\\n\\end{longtable}\n"


def test_tab02_unverifiable_when_protected_config_missing(tmp_path: Path) -> None:
    """No protected-files.yaml with a clean script -> UNVERIFIABLE (regression)."""
    project = _class_script_project(
        tmp_path, body=_TAB02_CLEAN_BODY, cls=_TAB02_CLS_OK, include_protected=False
    )
    context = _class_script_context(project, "TAB-02")
    outcome = Tab02LongtableContinuationRule().run(
        context, effective_rule("TAB-02", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.UNVERIFIABLE
    assert "не задаёт" not in finding.message


def test_tab02_untrusted_cls_without_macro_stays_unverifiable(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path, body=_TAB02_CLEAN_BODY, cls=_TAB02_CLS_MISSING_MACRO, include_protected=False
    )
    context = _class_script_context(project, "TAB-02")
    outcome = Tab02LongtableContinuationRule().run(
        context, effective_rule("TAB-02", layer="class+script")
    )
    assert outcome.findings[0].status is FindingStatus.UNVERIFIABLE


def test_tab02_warn_preserved_when_class_missing(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path,
        body=_TAB02_LONGTABLE_WITHOUT_HEADER,
        cls=_TAB02_CLS_MISSING_MACRO,
        include_protected=False,
    )
    context = _class_script_context(project, "TAB-02")
    outcome = Tab02LongtableContinuationRule().run(
        context, effective_rule("TAB-02", layer="class+script")
    )
    assert outcome.findings[0].status is FindingStatus.WARN


def test_tab02_fails_when_trusted_class_missing_macro(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path, body=_TAB02_CLEAN_BODY, cls=_TAB02_CLS_MISSING_MACRO, include_protected=True
    )
    context = _class_script_context(project, "TAB-02")
    outcome = Tab02LongtableContinuationRule().run(
        context, effective_rule("TAB-02", layer="class+script")
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.FAIL
    assert finding.message == "класс не задаёт vkrlongtable/endhead"


def test_tab02_passes_with_trusted_class_and_clean_script(tmp_path: Path) -> None:
    project = _class_script_project(
        tmp_path, body=_TAB02_CLEAN_BODY, cls=_TAB02_CLS_OK, include_protected=True
    )
    context = _class_script_context(project, "TAB-02")
    outcome = Tab02LongtableContinuationRule().run(
        context, effective_rule("TAB-02", layer="class+script")
    )
    assert outcome.findings[0].status is FindingStatus.PASS
