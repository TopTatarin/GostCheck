"""Generate D-05 LaTeX bibliography fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "tests" / "fixtures" / "latex"
BIB = LATEX / "bib"
PASS = LATEX / "pass"


def _protected_yaml() -> str:
    return (PASS / "protected-files.yaml").read_text(encoding="utf-8")


def _write_fixture(name: str, *, main_tex: str, refs_bib: str) -> None:
    target = BIB / name
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PASS / "gostcheck-vkr.cls", target / "gostcheck-vkr.cls")
    (target / "protected-files.yaml").write_text(_protected_yaml(), encoding="utf-8", newline="\n")
    (target / "main.tex").write_text(main_tex, encoding="utf-8", newline="\n")
    (target / "refs.bib").write_text(refs_bib, encoding="utf-8", newline="\n")


def _article(key: str, *, author: str, title: str, year: int, url: str = "", urldate: str = "") -> str:
    lines = [
        f"@article{{{key},",
        f"  author = {{{author}}},",
        f"  title = {{{title}}},",
        f"  journaltitle = {{Journal of Testing}},",
        f"  year = {{{year}}},",
    ]
    if url:
        lines.append(f"  url = {{{url}}},")
    if urldate:
        lines.append(f"  urldate = {{{urldate}}},")
    lines.append("}")
    return "\n".join(lines)


def _foreign_article(index: int, *, year: int) -> str:
    return _article(
        f"foreign{index:02d}",
        author=f"Smith, J.{index}",
        title=f"Peer-reviewed study {index}",
        year=year,
    )


def _russian_article(index: int, *, year: int) -> str:
    return _article(
        f"ru{index:02d}",
        author=f"Иванов, И. И.",
        title=f"Отечественное исследование {index}",
        year=year,
    )


def _online(key: str, *, with_urldate: bool) -> str:
    url = "https://example.org/manual"
    urldate = "2026-01-15" if with_urldate else ""
    return _article(
        key,
        author="Example Team",
        title="Online manual",
        year=2024,
        url=url,
        urldate=urldate,
    )


def _pass_bib() -> str:
    entries = [_online("online01", with_urldate=True)]
    entries.extend(_foreign_article(index, year=2024 if index % 2 else 2023) for index in range(1, 13))
    entries.extend(_russian_article(index, year=2024 if index % 2 else 2022) for index in range(1, 9))
    return "\n\n".join(entries) + "\n"


def _pass_review_cites() -> str:
    keys = [f"foreign{index:02d}" for index in range(1, 13)]
    keys.extend(f"ru{index:02d}" for index in range(1, 9))
    keys.append("online01")
    chunks = [", ".join(keys[index : index + 4]) for index in range(0, len(keys), 4)]
    lines = ["Обзор современных подходов."]
    for chunk in chunks:
        lines.append(f"\\cite{{{chunk}}}.")
    return "\n".join(lines)


def _pass_main() -> str:
    return (
        "\\documentclass{gostcheck-vkr}\n"
        "\\addbibresource{refs.bib}\n"
        "\\begin{document}\n"
        "\\section{Обзор НТИ}\n"
        f"{_pass_review_cites()}\n"
        "\\section{Заключение}\n"
        "Краткое заключение.\n"
        "\\end{document}\n"
    )


def main() -> None:
    if not PASS.is_dir():
        raise SystemExit("run scripts/generate_latex_fixtures.py first")
    BIB.mkdir(parents=True, exist_ok=True)
    pass_bib = _pass_bib()
    pass_main = _pass_main()
    _write_fixture("pass", main_tex=pass_main, refs_bib=pass_bib)
    _write_fixture(
        "fail_bib01",
        main_tex=pass_main.replace(
            "\\cite{foreign01",
            "\\footcite{foreign01",
            1,
        ),
        refs_bib=pass_bib,
    )
    _write_fixture(
        "fail_bib02",
        main_tex=pass_main.replace(
            "Обзор современных подходов.",
            "Обзор современных подходов [1].",
            1,
        ),
        refs_bib=pass_bib,
    )
    _write_fixture(
        "fail_bib03",
        main_tex=pass_main,
        refs_bib=pass_bib.replace("author = {Smith, J.1},", "", 1),
    )
    _write_fixture(
        "fail_bib04",
        main_tex=pass_main,
        refs_bib=pass_bib.replace("  urldate = {2026-01-15},", "", 1),
    )
    _write_fixture(
        "fail_bib05",
        main_tex=pass_main.replace("\\end{document}", "\\nocite{*}\\n\\end{document}"),
        refs_bib=pass_bib,
    )
    _write_fixture(
        "fail_rev01",
        main_tex=(
            "\\documentclass{gostcheck-vkr}\n"
            "\\addbibresource{refs.bib}\n"
            "\\begin{document}\n"
            "\\section{Обзор НТИ}\n"
            "\\cite{foreign01, foreign02, ru01}.\n"
            "\\section{Заключение}\n"
            "Краткое заключение.\n"
            "\\end{document}\n"
        ),
        refs_bib=pass_bib,
    )
    _write_fixture(
        "fail_rev02",
        main_tex=(
            "\\documentclass{gostcheck-vkr}\n"
            "\\addbibresource{refs.bib}\n"
            "\\begin{document}\n"
            "\\section{Обзор НТИ}\n"
            "\\cite{ru01, ru02, ru03, ru04, ru05, ru06, ru07, ru08}.\n"
            "\\section{Заключение}\n"
            "Краткое заключение.\n"
            "\\end{document}\n"
        ),
        refs_bib=pass_bib,
    )
    _write_fixture(
        "fail_rev03",
        main_tex=pass_main,
        refs_bib=pass_bib.replace("year = {2024}", "year = {2010}").replace(
            "year = {2023}", "year = {2010}"
        ),
    )
    _write_fixture(
        "fail_rev04",
        main_tex=pass_main.replace(
            "\\cite{foreign01",
            "\\cite{badsource",
            1,
        ),
        refs_bib=pass_bib
        + "\n\n"
        + _article(
            "badsource",
            author="Wiki Author",
            title="Bad source",
            year=2020,
            url="https://wikipedia.org/wiki/Test",
            urldate="2026-01-15",
        ),
    )
    _write_fixture(
        "fail_rev07",
        main_tex=(
            "\\documentclass{gostcheck-vkr}\n"
            "\\addbibresource{refs.bib}\n"
            "\\begin{document}\n"
            "\\section{Обзор НТИ}\n"
            + ("word " * 180)
            + "\n\\section{Заключение}\nКраткое заключение.\n\\end{document}\n"
        ),
        refs_bib=pass_bib,
    )
    print("fixtures=", sorted(path.name for path in BIB.iterdir() if path.is_dir()))


if __name__ == "__main__":
    main()
