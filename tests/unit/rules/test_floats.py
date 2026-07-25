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
from normocontrol.rules.figures import Fig01PlacementRule, Fig02FigureReferenceRule
from normocontrol.rules.formulas import Mth01NumberedEquationsRule
from normocontrol.rules.latex_source import LatexProjectReader
from normocontrol.rules.latex_symbols import (
    caption_arguments,
    contains_abbreviated_figure_reference,
    contains_unnumbered_display_math,
    figure_blocks,
    reference_targets,
)

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
