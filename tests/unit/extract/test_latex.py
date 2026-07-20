from __future__ import annotations

import os
import subprocess
import unicodedata
from pathlib import Path

import pytest

from normocontrol.extract.base import (
    IncludeCycleError,
    IncludeNotFoundError,
    SectionKind,
    UnsafePathError,
)
from normocontrol.extract.latex import LatexExtractor

ROOT = Path(__file__).parents[3]
MINIMAL = ROOT / "tests" / "fixtures" / "extract" / "minimal"


def write_tex(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_multifile_latex_is_expanded_in_source_order_and_sectioned() -> None:
    first = LatexExtractor(MINIMAL).extract(MINIMAL / "main.tex")
    second = LatexExtractor(MINIMAL).extract(MINIMAL / "main.tex")

    assert first == second
    assert [source.path for source in first.source_files] == [
        "main.tex",
        "sections/introduction.tex",
        "sections/conclusion.tex",
    ]
    assert first.text.casefold().index("введение") < first.text.casefold().index("заключение")
    assert {section.kind for section in first.sections} >= {
        SectionKind.INTRODUCTION,
        SectionKind.CONCLUSION,
    }
    assert {chunk.section_id for chunk in first.chunks} >= {"introduction", "conclusion"}


def test_comments_escaped_percent_and_literal_environments_are_safe(tmp_path: Path) -> None:
    write_tex(tmp_path / "secret.tex", "НЕ ДОЛЖЕН ПОПАСТЬ")
    main = write_tex(
        tmp_path / "main.tex",
        r"""
До \% после. % \input{secret}
\begin{verbatim}
literal % \input{secret}
\begin{verbatim}nested % value\end{verbatim}
\end{verbatim}
\begin{lstlisting}
% \include{secret}
\end{lstlisting}
""",
    )

    bundle = LatexExtractor(tmp_path).extract(main)

    assert "НЕ ДОЛЖЕН ПОПАСТЬ" not in bundle.text
    assert "До % после." in bundle.text
    assert "literal % \\input{secret}" in bundle.text
    assert "% \\include{secret}" in bundle.text
    assert [source.path for source in bundle.source_files] == ["main.tex"]


def test_include_cycle_and_missing_file_are_typed(tmp_path: Path) -> None:
    write_tex(tmp_path / "a.tex", r"\input{b}")
    write_tex(tmp_path / "b.tex", r"\include{a}")

    with pytest.raises(IncludeCycleError, match=r"a\.tex -> b\.tex -> a\.tex"):
        LatexExtractor(tmp_path).extract(tmp_path / "a.tex")

    write_tex(tmp_path / "missing-main.tex", r"\input{absent}")
    with pytest.raises(IncludeNotFoundError, match="absent"):
        LatexExtractor(tmp_path).extract(tmp_path / "missing-main.tex")


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    write_tex(tmp_path / "outside.tex", "outside")
    main = write_tex(root / "main.tex", r"\input{../outside}")

    with pytest.raises(UnsafePathError, match="outside project root"):
        LatexExtractor(root).extract(main)


def test_symlink_outside_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside_dir = tmp_path / "outside"
    write_tex(outside_dir / "outside.tex", "outside")
    link = root / "linked"
    try:
        os.symlink(outside_dir, link, target_is_directory=True)
    except OSError:
        # Directory junctions require no Windows developer-mode symlink privilege.
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside_dir)],
            check=True,
            capture_output=True,
        )
    main = write_tex(root / "main.tex", r"\input{linked/outside}")

    try:
        with pytest.raises(UnsafePathError, match="outside project root"):
            LatexExtractor(root).extract(main)
    finally:
        # Remove only the reparse point, never its external target.
        if link.exists() or link.is_symlink():
            os.rmdir(link)


def test_nfd_filename_and_cyrillic_label_are_preserved(tmp_path: Path) -> None:
    nfd_name = unicodedata.normalize("NFD", "Золоева") + ".tex"
    write_tex(
        tmp_path / nfd_name,
        r"\section{Аннотация}\label{секция:аннотация}Синтетический текст.",
    )
    main = write_tex(tmp_path / "main.tex", f"\\input{{{nfd_name}}}")

    bundle = LatexExtractor(tmp_path).extract(main)

    assert bundle.source_files[1].path == nfd_name
    assert any(section.kind is SectionKind.ANNOTATION for section in bundle.sections)
