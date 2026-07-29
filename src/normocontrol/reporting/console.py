"""Privacy-safe console summary for ``normocontrol run``."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from normocontrol.domain import ExitCode, FindingStatus, RunReport
from normocontrol.reporting.json_report import collect_findings
from normocontrol.reporting.redaction import redact_text
from normocontrol.rules.gate import evaluate_gate, is_formal_layer

EXIT_CODE_MEANINGS: Mapping[ExitCode, str] = {
    ExitCode.SUCCESS: "success; advisory findings do not block",
    ExitCode.RUNTIME_ERROR: "runtime command error",
    ExitCode.FORMAL_FAILURE: "formal gate failed",
    ExitCode.CONFIG_ERROR: "input or configuration error",
    ExitCode.INTERNAL_ERROR: "internal or tool error",
}


@dataclass(frozen=True, slots=True)
class ConsoleRunSummary:
    """Structured fields rendered after a CLI run."""

    source: str
    profile: str
    provider: str
    gate: str
    degraded: bool
    degraded_reason: str
    status_counts: tuple[tuple[str, int], ...]
    blocking_rule_ids: tuple[str, ...]
    report_md: str
    report_json: str
    report_md_generated: bool
    report_json_generated: bool
    exit_code: ExitCode


def safe_display_path(
    path: Path,
    *,
    base: Path | None = None,
    tail_parts: int = 1,
) -> str:
    """Return a useful path without exposing an absolute user directory."""
    resolved = path.resolve()
    display_base = (base or Path.cwd()).resolve()
    try:
        relative = resolved.relative_to(display_base)
    except ValueError:
        safe_tail = "/".join(resolved.parts[-max(1, tail_parts) :])
        return f"…/{redact_text(safe_tail) or '<unnamed>'}"
    return "." if not relative.parts else redact_text(relative.as_posix())


def _published_header(published: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if published is None:
        return {}
    header = published.get("header")
    return header if isinstance(header, Mapping) else {}


def _degraded_reason(report: RunReport, degraded: bool) -> str:
    if not degraded:
        return "none"
    rule_ids = sorted(
        {
            finding.rule_id
            for finding in collect_findings(report)
            if is_formal_layer(finding.layer) and finding.status is FindingStatus.UNVERIFIABLE
        }
    )
    if rule_ids:
        return f"formal checks unverifiable: {', '.join(rule_ids)}"
    return "pipeline reported incomplete extraction"


def build_console_summary(
    report: RunReport,
    *,
    source: Path,
    out_dir: Path,
    profile: str,
    provider: str,
    published: Mapping[str, Any] | None = None,
    display_base: Path | None = None,
) -> ConsoleRunSummary:
    """Build the success/formal-failure summary from structured results."""
    findings = collect_findings(report)
    counts = Counter(finding.status.value for finding in findings)
    status_counts = tuple((status.value, counts[status.value]) for status in FindingStatus)
    blocking = tuple(
        sorted({finding.rule_id for finding in evaluate_gate(findings).blocking_findings})
    )
    header = _published_header(published)
    degraded = bool(header.get("degraded", False))
    gate = "PASS" if report.exit_code is ExitCode.SUCCESS and not blocking else "FAIL"
    report_md = out_dir / "report.md"
    report_json = out_dir / "report.json"
    return ConsoleRunSummary(
        source=safe_display_path(source, base=display_base),
        profile=profile,
        provider=provider,
        gate=gate,
        degraded=degraded,
        degraded_reason=_degraded_reason(report, degraded),
        status_counts=status_counts,
        blocking_rule_ids=blocking,
        report_md=safe_display_path(report_md, base=display_base, tail_parts=2),
        report_json=safe_display_path(report_json, base=display_base, tail_parts=2),
        report_md_generated=report_md.is_file(),
        report_json_generated=report_json.is_file(),
        exit_code=report.exit_code,
    )


def build_error_console_summary(
    *,
    source: Path,
    out_dir: Path,
    profile: str,
    provider: str,
    exit_code: ExitCode,
    reason: str,
    display_base: Path | None = None,
) -> ConsoleRunSummary:
    """Build a diagnosable summary when no ``RunReport`` is available."""
    report_md = out_dir / "report.md"
    report_json = out_dir / "report.json"
    return ConsoleRunSummary(
        source=safe_display_path(source, base=display_base),
        profile=profile,
        provider=provider,
        gate="FAIL",
        degraded=False,
        degraded_reason=redact_text(reason),
        status_counts=tuple((status.value, 0) for status in FindingStatus),
        blocking_rule_ids=(),
        report_md=safe_display_path(report_md, base=display_base, tail_parts=2),
        report_json=safe_display_path(report_json, base=display_base, tail_parts=2),
        report_md_generated=False,
        report_json_generated=False,
        exit_code=exit_code,
    )


def render_console_summary(summary: ConsoleRunSummary) -> str:
    """Render a compact stable summary without finding messages or evidence."""
    counts = " ".join(f"{status}={count}" for status, count in summary.status_counts)
    blocking = (
        f"{len(summary.blocking_rule_ids)} ({', '.join(summary.blocking_rule_ids)})"
        if summary.blocking_rule_ids
        else "0"
    )

    def artifact(path: str, generated: bool) -> str:
        return path if generated else f"{path} (not generated)"

    meaning = EXIT_CODE_MEANINGS[summary.exit_code]
    return "\n".join(
        (
            "GostCheck run summary",
            f"input: {summary.source}",
            f"profile: {summary.profile}",
            f"provider: {summary.provider}",
            f"gate: {summary.gate}",
            f"degraded: {str(summary.degraded).lower()}",
            f"degraded_reason: {summary.degraded_reason}",
            f"counts: {counts}",
            f"blocking_findings: {blocking}",
            f"report.md: {artifact(summary.report_md, summary.report_md_generated)}",
            f"report.json: {artifact(summary.report_json, summary.report_json_generated)}",
            f"exit_code: {int(summary.exit_code)} ({meaning})",
        )
    )
