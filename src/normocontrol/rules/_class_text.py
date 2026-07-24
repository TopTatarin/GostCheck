"""Shared helpers for reading protected class files."""

from __future__ import annotations

from normocontrol.rules.context import ExecutionContext
from normocontrol.rules.protected_config import (
    default_protected_config_path,
    load_protected_files_config,
)


def class_file_text(context: ExecutionContext) -> str | None:
    """Read the primary protected class file for formal class-layer checks."""
    if context.latex is None:
        return None
    config = load_protected_files_config(default_protected_config_path(context.latex.root))
    if config is None or not config.class_files:
        return None
    relative = config.class_files[0].path
    path = context.latex.root / relative
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")
