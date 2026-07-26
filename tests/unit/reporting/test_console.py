"""Unit and snapshot tests for the privacy-safe run summary."""

from __future__ import annotations

from pathlib import Path

import pytest

from normocontrol.domain import (
    ExitCode,
    Finding,
    FindingStatus,
    RuleLayer,
    RunReport,
    Severity,
    StageResult,
)
from normocontrol.reporting.console import (
    ConsoleRunSummary,
    build_console_summary,
    build_error_console_summary,
    render_console_summary,
    safe_display_path,
)

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOTS = ROOT / "tests" / "snapshots"
STATUS_COUNTS = (
    ("pass", 3),
    ("fail", 0),
    ("warn", 0),
    ("info", 0),
    ("not_applicable", 1),
    ("unverifiable", 0),
    ("skipped", 0),
)


def _snapshot_summary(kind: str) -> ConsoleRunSummary:
    values: dict[str, object] = {
        "source": "tests/fixtures/demo/pass",
        "profile": "software",
        "provider": "disabled",
        "gate": "PASS",
        "degraded": False,
        "degraded_reason": "none",
        "status_counts": STATUS_COUNTS,
        "blocking_rule_ids": (),
        "report_md": "build/demo/report.md",
        "report_json": "build/demo/report.json",
        "report_md_generated": True,
        "report_json_generated": True,
        "exit_code": ExitCode.SUCCESS,
    }
    if kind == "fail":
        values.update(
            gate="FAIL",
            status_counts=(
                ("pass", 2),
                ("fail", 1),
                ("warn", 0),
                ("info", 0),
                ("not_applicable", 0),
                ("unverifiable", 0),
                ("skipped", 0),
            ),
            blocking_rule_ids=("STR-01",),
            exit_code=ExitCode.FORMAL_FAILURE,
        )
    elif kind == "advisory":
        values.update(
            status_counts=(
                ("pass", 2),
                ("fail", 0),
                ("warn", 1),
                ("info", 0),
                ("not_applicable", 0),
                ("unverifiable", 0),
                ("skipped", 0),
            )
        )
    elif kind == "degraded":
        values.update(
            gate="FAIL",
            degraded=True,
            degraded_reason="formal checks unverifiable: FMT-04",
            status_counts=(
                ("pass", 0),
                ("fail", 0),
                ("warn", 0),
                ("info", 0),
                ("not_applicable", 0),
                ("unverifiable", 1),
                ("skipped", 0),
            ),
            blocking_rule_ids=("FMT-04",),
            exit_code=ExitCode.FORMAL_FAILURE,
        )
    return ConsoleRunSummary(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["pass", "fail", "advisory", "degraded"])
def test_console_summary_snapshots(kind: str) -> None:
    rendered = render_console_summary(_snapshot_summary(kind))
    expected = (SNAPSHOTS / f"console-summary-{kind}.txt").read_text(encoding="utf-8")

    assert f"{rendered}\n" == expected


def test_build_summary_counts_statuses_and_never_prints_payload(tmp_path: Path) -> None:
    source = tmp_path / "ВКР с пробелами"
    out = tmp_path / "готовый отчёт"
    source.mkdir()
    out.mkdir()
    (out / "report.md").touch()
    (out / "report.json").touch()
    finding = Finding(
        rule_id="STR-01",
        layer=RuleLayer.SCRIPT,
        severity=Severity.ERROR,
        status=FindingStatus.FAIL,
        message="raw_prompt='FULL THESIS' api_key=sk-secret-value",
        path=str(tmp_path / "private" / "thesis.tex"),
    )
    report = RunReport(
        tool_version="0.1.0",
        exit_code=ExitCode.FORMAL_FAILURE,
        stages=(StageResult(name="formal", findings=(finding,)),),
    )

    summary = build_console_summary(
        report,
        source=source,
        out_dir=out,
        profile="research",
        provider="ollama",
        published={"header": {"degraded": False}},
        display_base=tmp_path,
    )
    rendered = render_console_summary(summary)

    assert "ВКР с пробелами" in rendered
    assert "готовый отчёт/report.md" in rendered
    assert "fail=1" in rendered
    assert "blocking_findings: 1 (STR-01)" in rendered
    assert "FULL THESIS" not in rendered
    assert "sk-secret-value" not in rendered
    assert str(tmp_path) not in rendered


def test_safe_display_path_shortens_external_absolute_path(tmp_path: Path) -> None:
    external = tmp_path / "Синтетический документ.pdf"
    base = tmp_path / "other"
    base.mkdir()

    displayed = safe_display_path(external, base=base)

    assert displayed == "…/Синтетический документ.pdf"
    assert str(tmp_path) not in displayed


def test_error_summary_does_not_claim_stale_reports(tmp_path: Path) -> None:
    out = tmp_path / "existing"
    out.mkdir()
    (out / "report.md").touch()
    (out / "report.json").touch()

    summary = build_error_console_summary(
        source=tmp_path / "missing.pdf",
        out_dir=out,
        profile="unknown",
        provider="disabled",
        exit_code=ExitCode.CONFIG_ERROR,
        reason=f"missing {tmp_path / 'document.pdf'}",
        display_base=tmp_path,
    )
    rendered = render_console_summary(summary)

    assert "degraded_reason: missing [REDACTED_PATH]" in rendered
    assert "report.md: existing/report.md (not generated)" in rendered
    assert "report.json: existing/report.json (not generated)" in rendered
