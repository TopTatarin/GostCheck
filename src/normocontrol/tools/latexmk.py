"""latexmk wrapper with log diagnostics."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from normocontrol.tools.subprocess import run_command

_OVERFULL_RE = re.compile(
    r"Overfull \\hbox .*?\((?P<points>[0-9.]+)pt too wide\)",
    re.IGNORECASE,
)
_MISSING_FILE_RE = re.compile(r"^! LaTeX Error: File `([^']+)' not found\.", re.MULTILINE)


class LatexBuildStatus(StrEnum):
    """High-level latexmk outcome."""

    SUCCESS = "success"
    COMPILE_ERROR = "compile_error"
    MISSING_DEPENDENCY = "missing_dependency"
    TOOL_MISSING = "tool_missing"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class LatexBuildResult:
    """Structured latexmk output."""

    status: LatexBuildStatus
    returncode: int
    log_excerpt: str
    overfull_hboxes_pt: tuple[float, ...] = ()
    missing_files: tuple[str, ...] = ()


class LatexmkRunner:
    """Run latexmk in an isolated working directory."""

    def __init__(self, *, latexmk_path: str | None = None, timeout_s: float = 120.0) -> None:
        self._latexmk = latexmk_path or "latexmk"
        self._timeout_s = timeout_s

    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        """Compile ``main_tex`` relative to ``project_root``."""
        if shutil.which(self._latexmk) is None:
            return LatexBuildResult(
                status=LatexBuildStatus.TOOL_MISSING,
                returncode=127,
                log_excerpt="latexmk executable not found",
            )
        relative = main_tex.resolve().relative_to(project_root.resolve())
        command = (
            self._latexmk,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            str(relative),
        )
        result = run_command(command, cwd=project_root, timeout_s=self._timeout_s)
        log_path = project_root / relative.with_suffix(".log")
        log_text = ""
        if log_path.is_file():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")[:256_000]
        combined = "\n".join(part for part in (result.stdout, result.stderr, log_text) if part)
        if result.executable_missing:
            return LatexBuildResult(
                status=LatexBuildStatus.TOOL_MISSING,
                returncode=result.returncode,
                log_excerpt=combined[:4000],
            )
        if result.timed_out:
            return LatexBuildResult(
                status=LatexBuildStatus.TIMEOUT,
                returncode=result.returncode,
                log_excerpt=combined[:4000],
            )
        missing = tuple(sorted(set(_MISSING_FILE_RE.findall(combined))))
        if missing:
            return LatexBuildResult(
                status=LatexBuildStatus.MISSING_DEPENDENCY,
                returncode=result.returncode,
                log_excerpt=combined[:4000],
                missing_files=missing,
            )
        overfull = tuple(
            sorted(
                {
                    float(match.group("points"))
                    for match in _OVERFULL_RE.finditer(combined)
                    if float(match.group("points")) > 15.0
                }
            )
        )
        if result.returncode != 0:
            return LatexBuildResult(
                status=LatexBuildStatus.COMPILE_ERROR,
                returncode=result.returncode,
                log_excerpt=combined[:4000],
                overfull_hboxes_pt=overfull,
            )
        return LatexBuildResult(
            status=LatexBuildStatus.SUCCESS,
            returncode=0,
            log_excerpt=combined[:4000],
            overfull_hboxes_pt=overfull,
        )


class LatexBuildService:
    """Indirection layer for tests."""

    def __init__(self, runner: LatexmkRunner | None = None) -> None:
        self._runner = runner or LatexmkRunner()

    def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
        return self._runner.build(project_root, main_tex)
