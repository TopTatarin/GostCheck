"""Build and validate the published JSON report document."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from normocontrol.domain import (
    ExitCode,
    Finding,
    FindingStatus,
    RuleLayer,
    RunReport,
    Severity,
)
from normocontrol.reporting.fingerprint import finding_fingerprint, normalize_finding_payload
from normocontrol.reporting.redaction import redact_structure
from normocontrol.rules.gate import (
    GateOutcome,
    evaluate_gate,
    finding_is_blocking_unverifiable,
    is_formal_layer,
)

SCHEMA_VERSION = "1.2"
GITHUB_SUMMARY_MARKER = "<!-- normocontrol-report -->"
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ReportMeta:
    """Header inputs that are not part of the raw RunReport stages."""

    commit_sha: str = "unknown"
    profile: str | None = None
    rubric_version: str | None = None
    model_id: str | None = None
    degraded: bool = False
    approvals_required: bool = False
    artifact_name: str | None = None
    repo_root: Path | None = None


def default_recommendation(finding: Finding) -> str:
    """Provide a short actionable hint without inventing domain expertise."""
    if finding.status is FindingStatus.FAIL:
        return "Исправьте нарушение и повторите formal-gate."
    if finding.status is FindingStatus.UNVERIFIABLE:
        return "Добавьте исходники/артефакты, необходимые для проверки правила."
    if finding.status is FindingStatus.WARN:
        return "Проверьте замечание перед финальной сдачей."
    if "APPROVAL_REQUIRED" in finding.message.upper():
        return "Дождитесь утверждения параметра кафедрой."
    return "Информационное замечание; merge не блокируется."


def _coerce_page(page: int | None) -> int | None:
    if page is None or page < 1:
        return None
    return page


def publish_finding(
    finding: Finding,
    *,
    repo_root: Path | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Convert a domain finding into the published report shape."""
    normalized = normalize_finding_payload(finding, repo_root=repo_root)
    page = _coerce_page(finding.page)
    if page is None:
        normalized.pop("page", None)
    else:
        normalized["page"] = page
    item = {
        **normalized,
        "fingerprint": finding_fingerprint(finding, repo_root=repo_root),
        "recommendation": default_recommendation(finding),
    }
    if confidence is not None:
        # Confidence is informational only and must never drive the gate.
        item["confidence"] = confidence
        item["confidence_note"] = "model confidence, not probability of truth"
    return item


def count_findings(findings: Sequence[Finding]) -> dict[str, int]:
    """Compute stable category counters for Markdown/summary headers."""
    formal_errors = 0
    warnings = 0
    llm_advisory = 0
    unverifiable = 0
    blocking_unverifiable = 0
    approvals_required = 0
    for finding in findings:
        if "APPROVAL_REQUIRED" in finding.message.upper():
            approvals_required += 1
        if finding.status is FindingStatus.UNVERIFIABLE:
            unverifiable += 1
            if finding_is_blocking_unverifiable(finding):
                blocking_unverifiable += 1
        if finding.layer in {RuleLayer.LLM, RuleLayer.VISION}:
            if finding.status in {FindingStatus.WARN, FindingStatus.INFO}:
                llm_advisory += 1
            continue
        if (
            is_formal_layer(finding.layer)
            and finding.severity is Severity.ERROR
            and finding.status is FindingStatus.FAIL
        ):
            formal_errors += 1
        elif finding.status is FindingStatus.WARN or finding.severity is Severity.WARN:
            warnings += 1
    return {
        "formal_errors": formal_errors,
        "warnings": warnings,
        "llm_advisory": llm_advisory,
        "unverifiable": unverifiable,
        "blocking_unverifiable": blocking_unverifiable,
        "approvals_required": approvals_required,
    }


def collect_findings(report: RunReport) -> tuple[Finding, ...]:
    """Flatten stage findings in stage order."""
    items: list[Finding] = []
    for stage in report.stages:
        items.extend(stage.findings)
    return tuple(items)


def gate_status_for(report: RunReport) -> str:
    """Map exit code / formal findings to a human gate label without changing it."""
    decision = evaluate_gate(collect_findings(report))
    if report.exit_code is ExitCode.FORMAL_FAILURE or decision.outcome is GateOutcome.FAIL:
        return "fail"
    if report.exit_code in {ExitCode.CONFIG_ERROR, ExitCode.INTERNAL_ERROR}:
        return "error"
    return "pass"


def build_published_report(
    report: RunReport,
    meta: ReportMeta,
    *,
    clock: Clock | None = None,
    confidence_by_rule: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Assemble the versioned published report document."""
    findings = collect_findings(report)
    published_findings = [
        publish_finding(
            finding,
            repo_root=meta.repo_root,
            confidence=(confidence_by_rule or {}).get(finding.rule_id),
        )
        for finding in findings
        if finding.status
        not in {FindingStatus.PASS, FindingStatus.SKIPPED, FindingStatus.NOT_APPLICABLE}
        or "APPROVAL_REQUIRED" in finding.message.upper()
    ]
    # Keep NOT_APPLICABLE/PASS out of the human report unless approval flagged;
    # still retain stages for machine consumers.
    stamp = (clock or (lambda: datetime.now(UTC)))().astimezone(UTC).replace(microsecond=0)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "header": {
            "commit_sha": meta.commit_sha,
            "profile": meta.profile,
            "rubric_version": meta.rubric_version,
            "model_id": meta.model_id,
            "tool_version": report.tool_version,
            "gate_status": gate_status_for(report),
            "degraded": meta.degraded,
            "approvals_required": meta.approvals_required
            or any("APPROVAL_REQUIRED" in f.message.upper() for f in findings),
            "generated_at": stamp.isoformat().replace("+00:00", "Z"),
            "artifact_name": meta.artifact_name,
        },
        "exit_code": int(report.exit_code),
        "counts": count_findings(findings),
        "findings": published_findings,
        "stages": json.loads(report.model_dump_json())["stages"],
    }
    return cast(dict[str, Any], redact_structure(payload))


def load_report_schema(schema_path: Path | None = None) -> dict[str, Any]:
    """Load ``schemas/report.schema.json`` from the repository."""
    path = schema_path or Path(__file__).resolve().parents[3] / "schemas" / "report.schema.json"
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def validate_published_report(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any] | None = None,
) -> None:
    """Validate published JSON against the versioned schema."""
    resolved = schema or load_report_schema()
    Draft202012Validator(resolved).validate(dict(payload))
