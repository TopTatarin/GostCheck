#!/usr/bin/env python3
"""Validate an untrusted consumer submission path inside its checkout."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath, PureWindowsPath


class SubmissionPathError(ValueError):
    """Raised when a consumer submission path violates the workflow contract."""


def _has_reparse_component(workspace: Path, relative: PurePosixPath) -> bool:
    current = workspace
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
        is_junction = getattr(current, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
    return False


def validate_submission_path(workspace: Path, submission: str) -> str:
    """Return a normalized relative path that cannot escape ``workspace``."""
    if not submission or "\x00" in submission:
        raise SubmissionPathError("submission_path must be non-empty and contain no NUL")
    if any(ord(character) < 32 for character in submission):
        raise SubmissionPathError("submission_path must not contain control characters")

    normalized_separators = submission.replace("\\", "/")
    posix_path = PurePosixPath(normalized_separators)
    windows_path = PureWindowsPath(submission)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise SubmissionPathError("submission_path must be relative to the workspace")
    if ".." in posix_path.parts:
        raise SubmissionPathError("submission_path must not contain '..'")
    if posix_path == PurePosixPath("."):
        raise SubmissionPathError("submission_path must name a project or document")

    workspace_resolved = workspace.resolve(strict=True)
    candidate = workspace_resolved.joinpath(*posix_path.parts)
    if _has_reparse_component(workspace_resolved, posix_path):
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(workspace_resolved)
        except ValueError as error:
            raise SubmissionPathError(
                "submission_path symlink or junction escapes the workspace"
            ) from error
    else:
        resolved = candidate.resolve(strict=True)

    try:
        relative = resolved.relative_to(workspace_resolved)
    except ValueError as error:
        raise SubmissionPathError("submission_path resolves outside the workspace") from error
    if not (resolved.is_dir() or resolved.suffix.casefold() in {".tex", ".pdf"}):
        raise SubmissionPathError(
            "submission_path must be a project directory, .tex file, or .pdf file"
        )
    return relative.as_posix()


def main() -> int:
    """CLI used by the reusable workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--submission", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    try:
        normalized = validate_submission_path(args.workspace, args.submission)
    except (OSError, SubmissionPathError) as error:
        print(f"ERROR invalid submission_path: {error}")
        return 3

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"submission_path={normalized}\n")
    else:
        print(normalized)
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
