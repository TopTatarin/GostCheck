from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
from pathlib import Path

import pytest

from normocontrol.errors import ConfigurationError, NormocontrolError
from normocontrol.logging import configure_logging

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = (
    ROOT
    / ".github"
    / "actions"
    / "setup-normocontrol"
    / "validate_submission_path.py"
)
SPEC = importlib.util.spec_from_file_location("validate_submission_path", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def test_configuration_error_uses_project_base_error() -> None:
    error = ConfigurationError("invalid profile")

    assert isinstance(error, NormocontrolError)
    assert str(error) == "invalid profile"


def test_configure_logging_selects_debug_level(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    configure_logging(verbose=True)

    assert captured["level"] == logging.DEBUG
    assert "%(message)s" in str(captured["format"])


@pytest.mark.parametrize(
    "submission",
    (
        "../outside.pdf",
        "project/../outside.pdf",
        "/tmp/outside.pdf",
        "C:\\private\\thesis.pdf",
        "\\\\server\\share\\thesis.pdf",
        "thesis.pdf\x00ignored",
        "thesis.pdf\nignored",
    ),
)
def test_submission_path_validator_rejects_untrusted_paths(
    tmp_path: Path,
    submission: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(VALIDATOR.SubmissionPathError):
        VALIDATOR.validate_submission_path(workspace, submission)


def test_submission_path_validator_accepts_real_consumer_fixture(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    fixture = workspace / "synthetic thesis" / "main.tex"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("\\documentclass{article}\n", encoding="utf-8")

    assert (
        VALIDATOR.validate_submission_path(workspace, "synthetic thesis/main.tex")
        == "synthetic thesis/main.tex"
    )


def test_submission_path_validator_rejects_symlink_or_junction_escape(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    link = workspace / "escaped"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("junction creation is unavailable")
    else:
        link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(VALIDATOR.SubmissionPathError, match="escapes"):
        VALIDATOR.validate_submission_path(workspace, "escaped/main.tex")
