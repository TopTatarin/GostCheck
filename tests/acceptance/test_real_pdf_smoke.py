"""Local acceptance checks for private PDFs supplied only through environment variables."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from normocontrol.domain import ExitCode
from normocontrol.reporting.json_report import validate_published_report

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "normocontrol.yaml.example"
RUBRIC = ROOT / "rubric.yaml"
TOP_LEVEL_FINDING_RE = re.compile(r"(?m)^- \*\*[A-Z]{3}-\d{2}\*\*")
ANY_FINDING_RE = re.compile(r"- \*\*[A-Z]{3}-\d{2}\*\*")
GLUED_FINDING_RE = re.compile(r"[^\r\n]- \*\*[A-Z]{3}-\d{2}\*\*")
TRUNCATED_GLUE_RE = re.compile(r"\[TRUNCATED\]- \*\*")

pytestmark = pytest.mark.acceptance


@pytest.mark.parametrize(
    ("env_name", "profile", "fmt05_status", "fmt05_page", "delta_range"),
    (
        ("GOSTCHECK_ACCEPTANCE_SOFTWARE_PDF", "software", "pass", 1, (0.0, 0.5)),
        ("GOSTCHECK_ACCEPTANCE_RESEARCH_PDF", "research", "fail", 39, (1.7, 1.8)),
        ("GOSTCHECK_ACCEPTANCE_MISIS_PDF", "software", "fail", 42, (2.5, 2.7)),
    ),
)
def test_real_pdf_report_separates_every_finding(
    tmp_path: Path,
    env_name: str,
    profile: str,
    fmt05_status: str,
    fmt05_page: int,
    delta_range: tuple[float, float],
) -> None:
    configured_path = os.environ.get(env_name)
    if not configured_path:
        pytest.skip(f"{env_name} is not configured")
    source = Path(configured_path)
    assert source.is_file(), f"{env_name} must point to an existing PDF"

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    env["PYTHONIOENCODING"] = "utf-8"
    completed_runs: list[subprocess.CompletedProcess[str]] = []
    out_dirs: list[Path] = []
    for run_number in (1, 2):
        out_dir = tmp_path / f"{profile}-{run_number}"
        out_dirs.append(out_dir)
        completed_runs.append(
            subprocess.run(
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
        )

    for completed in completed_runs:
        assert completed.returncode in {
            int(ExitCode.SUCCESS),
            int(ExitCode.FORMAL_FAILURE),
        }, f"unexpected CLI exit code: {completed.returncode}"
    markdown = (out_dirs[0] / "report.md").read_text(encoding="utf-8")
    top_level = TOP_LEVEL_FINDING_RE.findall(markdown)
    all_markers = ANY_FINDING_RE.findall(markdown)
    glued = GLUED_FINDING_RE.findall(markdown)

    assert "<details>" in markdown
    assert len(top_level) >= 2
    assert len(top_level) == len(all_markers)
    assert glued == []
    assert TRUNCATED_GLUE_RE.search(markdown) is None

    reports = [
        json.loads((out_dir / "report.json").read_text(encoding="utf-8")) for out_dir in out_dirs
    ]
    for report in reports:
        validate_published_report(report)
    fmt01_runs = [
        next(finding for finding in report["findings"] if finding["rule_id"] == "FMT-01")
        for report in reports
    ]
    assert fmt01_runs[0] == fmt01_runs[1]
    evidence_text = " ".join(
        item.get("description") or "" for item in fmt01_runs[0].get("evidence", [])
    )
    assert "body_chars=" in evidence_text
    assert "font_denominator=" in evidence_text
    assert "size_denominator=" in evidence_text
    assert "top_fonts=" in evidence_text
    assert "top_sizes=" in evidence_text
    assert "excluded=" in evidence_text
    assert "mismatch_pages=" in evidence_text
    assert "invalid_bbox=" in evidence_text
    assert "[TRUNCATED]" not in evidence_text

    fmt05_runs = [
        next(
            finding
            for stage in report["stages"]
            if stage["name"] == "formal"
            for finding in stage["findings"]
            if finding["rule_id"] == "FMT-05"
        )
        for report in reports
    ]
    assert fmt05_runs[0] == fmt05_runs[1]
    assert fmt05_runs[0]["status"] == fmt05_status
    assert fmt05_runs[0]["page"] == fmt05_page
    fmt05_evidence = " ".join(
        item.get("description") or "" for item in fmt05_runs[0].get("evidence", [])
    )
    assert "bbox=[" in fmt05_evidence
    assert "bounds=[" in fmt05_evidence
    assert "geometry_tolerance_pt=0.50" in fmt05_evidence
    delta_match = re.search(r"delta_pt=(\d+(?:\.\d+)?)", fmt05_evidence)
    assert delta_match is not None
    assert delta_range[0] <= float(delta_match.group(1)) <= delta_range[1]
