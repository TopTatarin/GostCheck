"""Generate D-04 LaTeX float fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "tests" / "fixtures" / "latex"
FLOATS = LATEX / "floats"
PASS = LATEX / "pass"


def _protected_yaml() -> str:
    return (PASS / "protected-files.yaml").read_text(encoding="utf-8")


def _write_fixture(name: str, main_tex: str) -> None:
    target = FLOATS / name
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PASS / "gostcheck-vkr.cls", target / "gostcheck-vkr.cls")
    (target / "protected-files.yaml").write_text(_protected_yaml(), encoding="utf-8", newline="\n")
    (target / "main.tex").write_text(main_tex, encoding="utf-8", newline="\n")


def _pass_main() -> str:
    return r"""\documentclass{gostcheck-vkr}
\begin{document}
\section{Математическая модель}
Дано: $x$ и $y$.
\begin{equation}
z = x + y
\end{equation}
\section{Архитектурно-техническое решение}
Система показана на \risref{fig:demo}.
\begin{figure}
\centering
Synthetic figure placeholder.
\caption{Рисунок 1 — Схема системы}
\label{fig:demo}
\end{figure}
\begin{table}
\caption{Таблица 1 — Параметры}
\label{tab:demo}
\begin{tabular}{ll}
A & B \\
\end{tabular}
\end{table}
См. таблицу~\ref{tab:demo}.
\end{document}
"""


def main() -> None:
    if not PASS.is_dir():
        raise SystemExit("run scripts/generate_latex_fixtures.py first")
    FLOATS.mkdir(parents=True, exist_ok=True)
    _write_fixture("pass", _pass_main())
    _write_fixture(
        "fail_fig02",
        _pass_main().replace("Система показана на \\risref{fig:demo}.", "Система без ссылки."),
    )
    _write_fixture(
        "fail_fig03",
        _pass_main().replace("\\risref{fig:demo}", "рис.~1"),
    )
    _write_fixture(
        "fail_cap01",
        _pass_main().replace(
            "Рисунок 1 — Схема системы",
            "рисунок 1 — схема системы.",
        ),
    )
    _write_fixture(
        "fail_mth01",
        _pass_main().replace(
            "\\begin{equation}\nz = x + y\n\\end{equation}",
            "\\[\nz = x + y\n\\]",
        ),
    )
    print("fixtures=", sorted(path.name for path in FLOATS.iterdir() if path.is_dir()))


if __name__ == "__main__":
    main()
