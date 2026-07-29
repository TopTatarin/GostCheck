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


def test_includegraphics_is_not_treated_as_include_dependency(tmp_path: Path) -> None:
    write_tex(tmp_path / "chapter.tex", "Included chapter.")
    main = write_tex(
        tmp_path / "main.tex",
        "\\includegraphics[width=\\textwidth]{figures/a.png}\n\\input{chapter}\n",
    )

    bundle = LatexExtractor(tmp_path).extract(main)

    assert [source.path for source in bundle.source_files] == ["main.tex", "chapter.tex"]
    assert "Included chapter." in bundle.text


@pytest.mark.parametrize(
    "directive",
    [
        r"\input{chapter}",
        r"\include{chapter}",
        r"\input chapter",
        r"\include chapter",
        "\\input \n {chapter}",
        "\\include\t\n chapter",
    ],
)
def test_input_and_include_argument_forms_are_recognized(
    tmp_path: Path,
    directive: str,
) -> None:
    write_tex(tmp_path / "chapter.tex", "Included chapter.")
    main = write_tex(tmp_path / "main.tex", directive)

    bundle = LatexExtractor(tmp_path).extract(main)

    assert [source.path for source in bundle.source_files] == ["main.tex", "chapter.tex"]
    assert "Included chapter." in bundle.text


@pytest.mark.parametrize(
    "directive",
    [
        r"\includegraphics[width=\textwidth]{figures/a.png}",
        r"\includegraphics*{a}",
        r"\includeonly{a}",
        r"\inputencoding{utf8}",
        r"\inputlineno",
        r"\includeCustom{a}",
        r"\inputCustom{a}",
        r"\includeпользовательская{a}",
        r"\inputпользовательская{a}",
        r"\include@internal{a}",
        r"\input@internal{a}",
    ],
)
def test_commands_with_input_or_include_prefix_are_not_dependencies(
    tmp_path: Path,
    directive: str,
) -> None:
    main = write_tex(tmp_path / "main.tex", directive)

    bundle = LatexExtractor(tmp_path).extract(main)

    assert [source.path for source in bundle.source_files] == ["main.tex"]


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
\begin{minted}{python}
# \input{secret}
\end{minted}
""",
    )

    bundle = LatexExtractor(tmp_path).extract(main)

    assert "НЕ ДОЛЖЕН ПОПАСТЬ" not in bundle.text
    assert "До % после." in bundle.text
    assert "literal % \\input{secret}" in bundle.text
    assert "% \\include{secret}" in bundle.text
    assert "# \\input{secret}" in bundle.text
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


def test_absolute_include_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = write_tex(tmp_path / "outside.tex", "outside")
    main = write_tex(root / "main.tex", f"\\input{{{outside.as_posix()}}}")

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
        if link.is_symlink():
            link.unlink()
        elif link.exists():
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


def test_nested_cyrillic_path_with_nfd_filename_is_resolved(tmp_path: Path) -> None:
    directory_name = "\u0440\u0430\u0437\u0434\u0435\u043b\u044b"
    nfd_name = unicodedata.normalize("NFD", "\u0433\u043b\u0430\u0432\u0430") + ".tex"
    relative = (Path(directory_name) / nfd_name).as_posix()
    write_tex(tmp_path / directory_name / nfd_name, "Nested chapter.")
    main = write_tex(tmp_path / "main.tex", f"\\input{{{relative}}}")

    bundle = LatexExtractor(tmp_path).extract(main)

    assert [source.path for source in bundle.source_files] == ["main.tex", relative]
    assert "Nested chapter." in bundle.text
