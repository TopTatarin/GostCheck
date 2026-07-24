"""Optional chktex wrapper."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from normocontrol.tools.subprocess import run_command


@dataclass(frozen=True, slots=True)
class ChktexResult:
    """Normalized chktex output."""

    available: bool
    returncode: int
    output: str


class ChktexRunner:
    """Run chktex against one TeX file when installed."""

    def __init__(self, *, chktex_path: str | None = None, timeout_s: float = 60.0) -> None:
        self._chktex = chktex_path or "chktex"
        self._timeout_s = timeout_s

    def lint(self, project_root: Path, main_tex: Path) -> ChktexResult:
        if shutil.which(self._chktex) is None:
            return ChktexResult(
                available=False,
                returncode=127,
                output="chktex executable not found",
            )
        relative = main_tex.resolve().relative_to(project_root.resolve())
        result = run_command(
            (self._chktex, "-q", "-n1", str(relative)),
            cwd=project_root,
            timeout_s=self._timeout_s,
        )
        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return ChktexResult(available=True, returncode=result.returncode, output=combined[:8000])
