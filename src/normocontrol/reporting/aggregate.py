"""Aggregate stage: publish JSON/Markdown/summary without changing the gate."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from normocontrol.cache import atomic_write_json, atomic_write_text
from normocontrol.domain import RunReport
from normocontrol.reporting.json_report import (
    Clock,
    ReportMeta,
    build_published_report,
    load_report_schema,
    validate_published_report,
)
from normocontrol.reporting.markdown import render_markdown, render_summary


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Paths written by the publisher."""

    report_json: Path
    report_md: Path
    summary_json: Path
    published: dict[str, Any]


def detect_commit_sha(*, cwd: Path | None = None) -> str:
    """Resolve commit SHA from CI env or local git without failing the report."""
    for key in ("GITHUB_SHA", "COMMIT_SHA"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if completed.returncode == 0:
        sha = completed.stdout.strip()
        return sha or "unknown"
    return "unknown"


def publish_reports(
    report: RunReport,
    out_dir: Path,
    *,
    meta: ReportMeta | None = None,
    clock: Clock | None = None,
    validate: bool = True,
    schema_path: Path | None = None,
) -> PublishResult:
    """Write ``report.json``, ``report.md`` and ``summary.json`` atomically.

    The publisher never mutates ``report.exit_code`` / gate decision.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = detect_commit_sha(cwd=out_dir)
    resolved_meta = meta or ReportMeta(
        commit_sha=sha,
        artifact_name=f"normocontrol-report-{sha[:7]}",
        repo_root=_guess_repo_root(out_dir),
    )
    if resolved_meta.commit_sha == "unknown" and sha != "unknown":
        resolved_meta = replace(resolved_meta, commit_sha=sha)
    if resolved_meta.repo_root is None:
        resolved_meta = replace(resolved_meta, repo_root=_guess_repo_root(out_dir))
    if not resolved_meta.artifact_name:
        resolved_meta = replace(
            resolved_meta,
            artifact_name=f"normocontrol-report-{resolved_meta.commit_sha[:7]}",
        )
    published = build_published_report(
        report,
        resolved_meta,
        clock=clock,
    )
    if validate:
        schema = load_report_schema(schema_path) if schema_path else load_report_schema()
        validate_published_report(published, schema=schema)

    report_json = out_dir / "report.json"
    report_md = out_dir / "report.md"
    summary_json = out_dir / "summary.json"
    markdown = render_markdown(published)
    summary_text = render_summary(published)
    atomic_write_json(report_json, published)
    atomic_write_text(report_md, markdown if markdown.endswith("\n") else f"{markdown}\n")
    atomic_write_json(
        summary_json,
        {
            "marker": "<!-- normocontrol-report -->",
            "gate_status": published["header"]["gate_status"],
            "exit_code": published["exit_code"],
            "counts": published["counts"],
            "markdown": summary_text,
            "artifact_name": published["header"].get("artifact_name"),
        },
    )
    return PublishResult(
        report_json=report_json,
        report_md=report_md,
        summary_json=summary_json,
        published=published,
    )


def _guess_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").exists():
            return candidate
        if (candidate / "rubric.yaml").exists() and (candidate / "pyproject.toml").exists():
            return candidate
    return None
