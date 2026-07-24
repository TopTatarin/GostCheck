"""Generate D-02 LaTeX fixtures (developer utility)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from normocontrol.extract.base import sha256_bytes

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "latex"
CONFIG = ROOT / "config"

CLS = textwrap.dedent(
    r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{gostcheck-vkr}[2025/01/01 GostCheck fixture class]
\LoadClass{article}
\RequirePackage{fontspec}
\setmainfont{Times New Roman}
\RequirePackage{titlesec}
\RequirePackage{setspace}
\onehalfspacing
\setlength{\parindent}{12.5mm}
\RequirePackage[left=30mm,right=10mm,top=20mm,bottom=20mm]{geometry}
\RequirePackage{caption}
\captionsetup[figure]{labelsep=endash,position=below,justification=centering,font={stretch=1},hyphenpenalty=10000}
\captionsetup[table]{position=top,singlelinecheck=off,justification=raggedright}
\newcommand{\risref}[1]{рисунке~\ref{#1}}
\newcommand{\vkrlongtable}[1]{\begin{longtable}{#1}\endfirsthead}
\RequirePackage{chngcntr}
\counterwithin{figure}{section}
\counterwithin{table}{section}
\RequirePackage{amsmath}
\RequirePackage{longtable}
\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex-gost}
"""
).strip() + "\n"
CLS_HASH = sha256_bytes(CLS.encode("utf-8"))

SECTIONS: tuple[str, ...] = (
    "Аннотация",
    "Введение",
    "Обзор НТИ",
    "Структурный системный анализ",
    "Постановка задачи",
    "Архитектурно-техническое решение",
    "Математическая модель",
    "Алгоритм",
    "Программная реализация",
    "Анализ результатов",
    "Заключение",
    "Список источников",
    "Приложения",
)


def protected_yaml(*, include_forbidden: bool = False) -> str:
    forbidden = ""
    if include_forbidden:
        forbidden = (
            "forbidden_preamble:\n"
            '  - pattern: "[\\\\]usepackage\\\\s*\\\\{geometry\\\\}"\n'
            '    message: "запрещён \\\\usepackage{geometry} в преамбуле"\n'
        )
    return (
        f"version: 1\n"
        f"class_files:\n"
        f"  - path: gostcheck-vkr.cls\n"
        f"    sha256: {CLS_HASH}\n"
        f"{forbidden}"
        f"allowed_renewcommand: []\n"
    )


def main_tex(
    *,
    preamble_extra: str = "",
    body_extra: str = "",
    section_extra: dict[str, str] | None = None,
    section_order: tuple[str, ...] | None = None,
) -> str:
    order = section_order or SECTIONS
    extra = section_extra or {}
    parts: list[str] = []
    for title in order:
        body = extra.get(title, f"Синтетический текст раздела «{title}» для fixture GostCheck.")
        parts.append(f"\\section{{{title}}}\n{body}\n")
    body = "".join(parts)
    return (
        f"\\documentclass{{gostcheck-vkr}}\n"
        f"{preamble_extra}"
        f"\\begin{{document}}\n"
        f"{body}"
        f"{body_extra}"
        f"\\end{{document}}\n"
    )


def write_fixture(
    name: str,
    main: str,
    *,
    protected: bool = True,
    cls_content: str = CLS,
) -> None:
    target = FIXTURES / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "main.tex").write_text(main, encoding="utf-8", newline="\n")
    (target / "gostcheck-vkr.cls").write_text(cls_content, encoding="utf-8", newline="\n")
    if protected:
        (target / "protected-files.yaml").write_text(
            protected_yaml(include_forbidden=False),
            encoding="utf-8",
            newline="\n",
        )


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    CONFIG.mkdir(parents=True, exist_ok=True)

    write_fixture("pass", main_tex())
    write_fixture("fail_sys01", main_tex(), cls_content=CLS + "% tampered\n")
    write_fixture("fail_sys02", main_tex(preamble_extra="\\usepackage{geometry}\n"))
    write_fixture(
        "fail_str01",
        main_tex(section_order=(SECTIONS[1], SECTIONS[0], *SECTIONS[2:])),
    )
    write_fixture("fail_str02", main_tex(body_extra="\\subsubsection{Лишняя вложенность}\n"))
    write_fixture(
        "fail_ann02",
        main_tex(section_extra={"Аннотация": "\\begin{itemize}\\item пункт\\end{itemize}"}),
    )
    write_fixture(
        "fail_int02",
        main_tex(section_extra={"Введение": "\\begin{enumerate}\\item пункт\\end{enumerate}"}),
    )
    (CONFIG / "protected-files.example.yaml").write_text(
        protected_yaml(include_forbidden=True),
        encoding="utf-8",
        newline="\n",
    )
    print(f"cls_hash={CLS_HASH}")
    print("fixtures=", sorted(path.name for path in FIXTURES.iterdir() if path.is_dir()))


if __name__ == "__main__":
    main()
