"""Local acceptance checks for private PDFs supplied only through environment variables."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from normocontrol.domain import ExitCode

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "normocontrol.yaml.example"
RUBRIC = ROOT / "rubric.yaml"
TOP_LEVEL_FINDING_RE = re.compile(r"(?m)^- \*\*[A-Z]{3}-\d{2}\*\*")
ANY_FINDING_RE = re.compile(r"- \*\*[A-Z]{3}-\d{2}\*\*")
GLUED_FINDING_RE = re.compile(r"[^\r\n]- \*\*[A-Z]{3}-\d{2}\*\*")
TRUNCATED_GLUE_RE = re.compile(r"\[TRUNCATED\]- \*\*")

pytestmark = pytest.mark.acceptance


@pytest.mark.parametrize(
    ("env_name", "profile"),
    (
        ("GOSTCHECK_ACCEPTANCE_SOFTWARE_PDF", "software"),
        ("GOSTCHECK_ACCEPTANCE_RESEARCH_PDF", "research"),
    ),
)
def test_real_pdf_report_separates_every_finding(
    tmp_path: Path,
    env_name: str,
    profile: str,
) -> None:
    configured_path = os.environ.get(env_name)
    if not configured_path:
        pytest.skip(f"{env_name} is not configured")
    source = Path(configured_path)
    assert source.is_file(), f"{env_name} must point to an existing PDF"

    out_dir = tmp_path / profile
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "normocontrol.cli",
            "run",
            str(source),
            "--config",
            str(CONFIG),
            "--rubric",
            str(RUBRIC),
            "--out",
            str(out_dir),
            "--profile",
            profile,
            "--no-llm",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )

    assert completed.returncode in {
        int(ExitCode.SUCCESS),
        int(ExitCode.FORMAL_FAILURE),
    }, f"unexpected CLI exit code: {completed.returncode}"
    markdown = (out_dir / "report.md").read_text(encoding="utf-8")
    top_level = TOP_LEVEL_FINDING_RE.findall(markdown)
    all_markers = ANY_FINDING_RE.findall(markdown)
    glued = GLUED_FINDING_RE.findall(markdown)

    assert "<details>" in markdown
    assert len(top_level) >= 2
    assert len(top_level) == len(all_markers)
    assert glued == []
    assert TRUNCATED_GLUE_RE.search(markdown) is None
