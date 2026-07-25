from __future__ import annotations

import os
import subprocess
import unicodedata
from pathlib import Path

import pytest

from normocontrol.extract.base import UnsafePathError
from normocontrol.extract.latex import LatexExtractor


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (r"\addbibresource{refs.bib}", ("refs.bib",)),
        (r"\addbibresource[location=local]{refs}", ("refs.bib",)),
        (r"\bibliography{b,a.bib}", ("a.bib", "b.bib")),
        (r"\addbibresource{refs\windows}", ("refs/windows.bib",)),
        (r"\addbibresource{refs/posix}", ("refs/posix.bib",)),
    ],
)
def test_bibliography_commands_resolve_portably(
    tmp_path: Path,
    command: str,
    expected: tuple[str, ...],
) -> None:
    main = _write(tmp_path / "main.tex", command)
    for relative in expected:
        _write(tmp_path / Path(relative), "")

    paths = LatexExtractor(tmp_path).discover_bibliography_paths(main)

    assert tuple(path.relative_to(tmp_path).as_posix() for path in paths) == expected


def test_repeated_resources_are_deduplicated_in_stable_posix_order(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "\n".join(
            (
                r"\addbibresource{z.bib}",
                r"\bibliography{a,z}",
                r"\addbibresource{./a.bib}",
            )
        ),
    )
    _write(tmp_path / "a.bib")
    _write(tmp_path / "z.bib")

    paths = LatexExtractor(tmp_path).discover_bibliography_paths(main)

    assert tuple(path.name for path in paths) == ("a.bib", "z.bib")


def test_bibliography_command_in_reachable_include_is_discovered(tmp_path: Path) -> None:
    main = _write(tmp_path / "main.tex", r"\input{sections/body}")
    _write(tmp_path / "sections" / "body.tex", r"\addbibresource{refs.bib}")
    _write(tmp_path / "refs.bib")

    paths = LatexExtractor(tmp_path).discover_bibliography_paths(main)

    assert tuple(path.name for path in paths) == ("refs.bib",)


def test_missing_and_commented_resources_are_not_executed(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "% \\addbibresource{../outside.bib}\n"
        "\\addbibresource{missing}\n"
        "\\begin{verbatim}\\addbibresource{/outside.bib}\\end{verbatim}\n",
    )

    assert LatexExtractor(tmp_path).discover_bibliography_paths(main) == ()


def test_bibliography_path_traversal_is_rejected(tmp_path: Path) -> None:
    main = _write(tmp_path / "main.tex", "\\addbibresource{../outside.bib}\n")

    with pytest.raises(UnsafePathError, match="bibliography"):
        LatexExtractor(tmp_path).discover_bibliography_paths(main)


def test_absolute_bibliography_path_is_rejected(tmp_path: Path) -> None:
    absolute = (tmp_path / "outside.bib").resolve()
    main = _write(tmp_path / "main.tex", f"\\addbibresource{{{absolute}}}\n")

    with pytest.raises(UnsafePathError, match="bibliography"):
        LatexExtractor(tmp_path).discover_bibliography_paths(main)


def test_directory_link_outside_project_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    _write(outside / "refs.bib")
    link = root / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    main = _write(root / "main.tex", r"\addbibresource{linked/refs.bib}")

    try:
        with pytest.raises(UnsafePathError, match="outside project root"):
            LatexExtractor(root).discover_bibliography_paths(main)
    finally:
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            os.rmdir(link)


def test_nfd_and_empty_bibliography_are_preserved(tmp_path: Path) -> None:
    name = unicodedata.normalize("NFD", "Источники") + ".bib"
    _write(tmp_path / name, "")
    main = _write(tmp_path / "main.tex", f"\\addbibresource{{{name}}}\n")

    paths = LatexExtractor(tmp_path).discover_bibliography_paths(main)

    assert len(paths) == 1
    assert paths[0].name == name
    assert paths[0].read_bytes() == b""


def test_fallback_search_is_safe_and_deterministic(tmp_path: Path) -> None:
    main = _write(tmp_path / "main.tex", "Synthetic document without a command.\n")
    _write(tmp_path / "z" / "refs.bib")
    _write(tmp_path / "a.bib")

    paths = LatexExtractor(tmp_path).discover_bibliography_paths(main)

    assert tuple(path.relative_to(tmp_path).as_posix() for path in paths) == (
        "a.bib",
        "z/refs.bib",
    )
