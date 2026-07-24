"""Execution inputs shared by all formal rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from normocontrol.extract.base import DocumentBundle, SourceFormat
from normocontrol.rubric.models import EffectiveRubric, NormocontrolConfig


class SourceKind(StrEnum):
    """Input artifacts required before a rule may run."""

    LATEX_PROJECT = "latex_project"
    BIB_FILES = "bib_files"
    PDF = "pdf"
    COMPILED_PDF = "compiled_pdf"


@dataclass(frozen=True, slots=True)
class LatexProject:
    """Safe LaTeX project metadata without embedding thesis text."""

    root: Path
    main_tex: Path


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Immutable view of one formal check run."""

    rubric: EffectiveRubric
    config: NormocontrolConfig
    bundle: DocumentBundle | None
    latex: LatexProject | None
    pdf_path: Path | None
    bib_paths: tuple[Path, ...]
    fail_closed: bool = False
    canceled: bool = False

    def has_source(self, kind: SourceKind) -> bool:
        """Report whether the requested source artifact is available."""
        if kind is SourceKind.LATEX_PROJECT:
            return self.latex is not None
        if kind is SourceKind.BIB_FILES:
            return bool(self.bib_paths)
        if kind is SourceKind.PDF:
            if self.pdf_path is not None:
                return True
            return self.bundle is not None and self.bundle.source_format is SourceFormat.PDF
        if kind is SourceKind.COMPILED_PDF:
            return self.pdf_path is not None
        return False

    def missing_sources(self, required: frozenset[SourceKind]) -> tuple[SourceKind, ...]:
        """Return required sources that are not present, in stable order."""
        return tuple(kind for kind in SourceKind if kind in required and not self.has_source(kind))

    @property
    def pdf_only(self) -> bool:
        """True when only a PDF artifact is available (no LaTeX project)."""
        if self.latex is not None:
            return False
        if self.bundle is not None and self.bundle.source_format is SourceFormat.LATEX:
            return False
        return self.pdf_path is not None or (
            self.bundle is not None and self.bundle.source_format is SourceFormat.PDF
        )
