"""Safe subprocess execution without shell interpolation."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Normalized subprocess output."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    executable_missing: bool = False


def run_command(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout_s: float,
    max_output_bytes: int = 256_000,
) -> CommandResult:
    """Run a command with bounded output and no shell."""
    if not argv:
        raise ValueError("argv must not be empty")
    if shutil.which(argv[0]) is None:
        return CommandResult(
            argv=argv,
            returncode=127,
            stdout="",
            stderr=f"executable not found: {argv[0]}",
            executable_missing=True,
        )
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = str(error.stdout or "")[:max_output_bytes]
        stderr = str(error.stderr or "")[:max_output_bytes]
        return CommandResult(
            argv=argv,
            returncode=124,
            stdout=stdout,
            stderr=stderr or "command timed out",
            timed_out=True,
        )
    stdout = (completed.stdout or "")[:max_output_bytes]
    stderr = (completed.stderr or "")[:max_output_bytes]
    return CommandResult(
        argv=argv,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )
