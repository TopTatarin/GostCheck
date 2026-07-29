from __future__ import annotations

import os
import subprocess
import unicodedata
from pathlib import Path

import pytest

from normocontrol.errors import ConfigurationError
from normocontrol.submission import resolve_submission, validate_latex_bundle


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_existing_pdf_file_is_accepted() -> None:
    source = Path(__file__).parents[1] / "fixtures" / "pdf" / "fmt_pass.pdf"

    submission = resolve_submission(source)

    assert submission.source == source.resolve()
    assert submission.root == source.parent.resolve()


def test_directory_with_top_level_main_tex_is_preferred_over_nested_samples(
    tmp_path: Path,
) -> None:
    main = _write(tmp_path / "main.tex", r"\documentclass{article}")
    _write(tmp_path / "samples" / "main.tex", r"\documentclass{article}")

    submission = resolve_submission(tmp_path)

    assert submission.source == main.resolve()
    assert submission.root == tmp_path.resolve()


def test_single_nested_main_tex_is_discovered(tmp_path: Path) -> None:
    main = _write(tmp_path / "submission" / "main.tex", r"\documentclass{article}")

    submission = resolve_submission(tmp_path)

    assert submission.source == main.resolve()
    assert submission.root == tmp_path.resolve()


def test_explicit_relative_root_supports_cyrillic_and_nfd(tmp_path: Path) -> None:
    nfd_name = unicodedata.normalize("NFD", "главный") + ".tex"
    relative = Path("разделы") / nfd_name
    main = _write(tmp_path / relative, r"\documentclass{article}")

    submission = resolve_submission(tmp_path, root=relative)

    assert submission.source == main.resolve()
    assert submission.root == tmp_path.resolve()
    assert submission.relative_source == relative.as_posix()


@pytest.mark.parametrize("with_fragment", [False, True])
def test_directory_without_root_is_actionable_and_privacy_safe(
    tmp_path: Path,
    with_fragment: bool,
) -> None:
    secret = "PRIVATE-DOCUMENT-CONTENT"
    if with_fragment:
        _write(tmp_path / "chapter.tex", secret)

    with pytest.raises(ConfigurationError) as raised:
        resolve_submission(tmp_path)

    message = str(raised.value)
    assert "root main.tex not found" in message
    assert "--root" in message
    assert "complete LaTeX project bundle" in message
    assert str(tmp_path.resolve()) not in message
    assert secret not in message


def test_multiple_nested_roots_are_rejected_in_deterministic_relative_order(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "z" / "main.tex")
    _write(tmp_path / "а" / "main.tex")

    messages: list[str] = []
    for _ in range(2):
        with pytest.raises(ConfigurationError) as raised:
            resolve_submission(tmp_path)
        messages.append(str(raised.value))

    assert messages[0] == messages[1]
    assert "multiple LaTeX roots found" in messages[0]
    assert "z/main.tex" in messages[0]
    assert "а/main.tex" in messages[0]
    assert str(tmp_path.resolve()) not in messages[0]


@pytest.mark.parametrize(
    ("root", "match"),
    [
        (Path("../outside.tex"), "traversal"),
        (Path("C:/outside.tex"), "relative"),
    ],
)
def test_explicit_root_rejects_traversal_and_absolute_paths(
    tmp_path: Path,
    root: Path,
    match: str,
) -> None:
    with pytest.raises(ConfigurationError, match=match):
        resolve_submission(tmp_path, root=root)


def test_explicit_root_rejects_link_outside_submission(tmp_path: Path) -> None:
    submission = tmp_path / "submission"
    submission.mkdir()
    outside = _write(tmp_path / "outside.tex", r"\documentclass{article}")
    link = submission / "root.tex"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(ConfigurationError, match="outside submission root"):
        resolve_submission(submission, root=Path("root.tex"))


@pytest.mark.parametrize(
    ("command", "kind", "dependency"),
    [
        (r"\input{chapters/missing}", "include", "chapters/missing.tex"),
        (r"\documentclass{custom-thesis}", "class", "custom-thesis.cls"),
        (r"\usepackage{styles/custom}", "style", "styles/custom.sty"),
        (r"\addbibresource{bib/missing.bib}", "bibliography", "bib/missing.bib"),
        (r"\includegraphics{images/missing}", "image", "images/missing"),
    ],
)
def test_missing_dependencies_have_separate_actionable_diagnostics(
    tmp_path: Path,
    command: str,
    kind: str,
    dependency: str,
) -> None:
    main = _write(tmp_path / "main.tex", command)

    with pytest.raises(ConfigurationError) as raised:
        validate_latex_bundle(tmp_path, main)

    message = str(raised.value)
    assert f"missing {kind}" in message
    assert dependency in message
    assert str(tmp_path.resolve()) not in message


def test_commented_dependencies_are_not_active(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "% \\input{missing}\n"
        "% \\includegraphics{private.png}\n"
        "% \\addbibresource{secret.bib}\n"
        "\\begin{verbatim}\\usepackage{styles/missing}\\end{verbatim}\n"
        "\\documentclass{article}\n",
    )

    assert validate_latex_bundle(tmp_path, main) == ()


def test_dependency_diagnostics_are_stable_and_do_not_expose_contents(
    tmp_path: Path,
) -> None:
    secret = "SECRET-THESIS-PARAGRAPH"
    main = _write(
        tmp_path / "main.tex",
        f"{secret}\n"
        "\\includegraphics{z-image}\n"
        "\\input{a-chapter}\n"
        "\\addbibresource{m-refs.bib}\n",
    )

    messages: list[str] = []
    for _ in range(2):
        with pytest.raises(ConfigurationError) as raised:
            validate_latex_bundle(tmp_path, main)
        messages.append(str(raised.value))

    assert messages[0] == messages[1]
    assert secret not in messages[0]
    assert str(tmp_path.resolve()) not in messages[0]


def test_dependency_symlink_outside_submission_is_rejected(tmp_path: Path) -> None:
    submission = tmp_path / "submission"
    submission.mkdir()
    outside = _write(tmp_path / "outside.tex", "outside")
    link = submission / "linked.tex"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("file symlinks are unavailable")
    main = _write(submission / "main.tex", r"\input{linked}")

    with pytest.raises(ConfigurationError, match="outside submission root"):
        validate_latex_bundle(submission, main)


def test_dependency_directory_link_outside_submission_is_rejected(tmp_path: Path) -> None:
    submission = tmp_path / "submission"
    submission.mkdir()
    outside = tmp_path / "outside"
    _write(outside / "chapter.tex", "outside")
    link = submission / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    main = _write(submission / "main.tex", r"\input{linked/chapter}")

    try:
        with pytest.raises(ConfigurationError, match="outside submission root"):
            validate_latex_bundle(submission, main)
    finally:
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            os.rmdir(link)
