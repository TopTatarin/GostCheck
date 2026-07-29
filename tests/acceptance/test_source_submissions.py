"""Opt-in acceptance checks for source projects supplied outside the repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from normocontrol.domain import ExitCode

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "normocontrol.yaml.example"
RUBRIC = ROOT / "rubric.yaml"
SALARY_SHA = "7532373195a841101d40ccf953cbdf59a103ce8d"

pytestmark = pytest.mark.acceptance


def _configured_directory(env_name: str) -> Path:
    configured = os.environ.get(env_name)
    if not configured:
        pytest.skip(f"{env_name} is not configured; external source acceptance is opt-in")
    path = Path(configured)
    assert path.is_dir(), f"{env_name} must point to an existing directory"
    return path


def _run_source(source: Path, out_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "normocontrol.cli",
            "--no-llm",
            "run",
            str(source),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out_dir),
            "--only",
            "BIB",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )


@pytest.mark.parametrize(
    "env_name",
    (
        "GOSTCHECK_ACCEPTANCE_MISIS_SOURCE",
        "GOSTCHECK_ACCEPTANCE_SALARY_SOURCE",
    ),
)
def test_complete_external_source_project_is_discovered(
    tmp_path: Path,
    env_name: str,
) -> None:
    source = _configured_directory(env_name)
    if env_name == "GOSTCHECK_ACCEPTANCE_SALARY_SOURCE":
        revision = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        assert revision == SALARY_SHA

    completed = _run_source(source, tmp_path / env_name.casefold())
    output = completed.stdout + completed.stderr

    assert completed.returncode in {
        int(ExitCode.SUCCESS),
        int(ExitCode.FORMAL_FAILURE),
    }, output
    assert "textwidth]" not in output
    report = json.loads(
        (tmp_path / env_name.casefold() / "report.json").read_text(encoding="utf-8")
    )
    if shutil.which("latexmk") is None:
        build = next(stage for stage in report["stages"] if stage["name"] == "build")
        assert any(
            finding["rule_id"] == "SYS-03"
            and finding["status"] == "unverifiable"
            and "latexmk" in finding["message"]
            for finding in build["findings"]
        )


def test_incomplete_external_sections_are_rejected_with_exit_three(tmp_path: Path) -> None:
    source = _configured_directory("GOSTCHECK_ACCEPTANCE_SECTIONS_SOURCE")

    completed = _run_source(source, tmp_path / "sections")
    output = completed.stdout + completed.stderr

    assert completed.returncode == int(ExitCode.CONFIG_ERROR)
    assert "root main.tex not found" in output
    assert "--root" in output
    assert "complete LaTeX project bundle" in output
    assert str(source.resolve()) not in output
