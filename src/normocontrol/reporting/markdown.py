"""Markdown and GitHub summary rendering for published reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from normocontrol.reporting.json_report import GITHUB_SUMMARY_MARKER
from normocontrol.reporting.redaction import sanitize_evidence_text

# GitHub issue/PR comment hard limit.
GITHUB_COMMENT_LIMIT = 65_536
# Leave headroom for wrapper UI chrome.
DEFAULT_SUMMARY_LIMIT = 60_000

_FORMAL_LAYERS = frozenset({"class", "script", "class+script"})


def _sanitize_code_span(value: object) -> str:
    return sanitize_evidence_text(str(value)).replace(r"\`", "'")


def _template_env(templates_dir: Path | None = None) -> Environment:
    root = templates_dir or Path(__file__).resolve().parents[3] / "templates"
    return Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def group_findings(findings: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split published findings into Markdown sections."""
    groups: dict[str, list[dict[str, Any]]] = {
        "formal_errors": [],
        "warnings": [],
        "llm_advisory": [],
        "unverifiable": [],
        "approvals_required": [],
    }
    for raw in findings:
        item = dict(raw)
        message = str(item.get("message", ""))
        status = str(item.get("status", ""))
        layer = str(item.get("layer", ""))
        severity = str(item.get("severity", ""))
        evidence = []
        for entry in item.get("evidence", []) or []:
            quote = entry.get("description") or entry.get("quote") or ""
            evidence.append(
                {
                    "locator": _sanitize_code_span(entry.get("locator", "")),
                    "quote": sanitize_evidence_text(str(quote)),
                }
            )
        item["evidence"] = evidence
        for key in ("rule_id", "severity", "status", "fingerprint", "recommendation"):
            item[key] = sanitize_evidence_text(str(item.get(key, "")))
        item["message"] = sanitize_evidence_text(message)
        if "APPROVAL_REQUIRED" in message.upper():
            groups["approvals_required"].append(item)
        if status == "unverifiable":
            groups["unverifiable"].append(item)
        if layer in {"llm", "vision"}:
            groups["llm_advisory"].append(item)
            continue
        if layer in _FORMAL_LAYERS and severity == "error" and status == "fail":
            groups["formal_errors"].append(item)
        elif status == "warn" or severity == "warn":
            groups["warnings"].append(item)
    return groups


def render_markdown(
    published: Mapping[str, Any],
    *,
    templates_dir: Path | None = None,
    collapse_after: int = 8,
) -> str:
    """Render ``report.md`` from the published JSON document."""
    env = _template_env(templates_dir)
    template = env.get_template("report.md.j2")
    groups = group_findings(list(published.get("findings", [])))
    return template.render(
        marker=GITHUB_SUMMARY_MARKER,
        header=published.get("header", {}),
        counts=published.get("counts", {}),
        exit_code=published.get("exit_code", 0),
        groups=groups,
        collapse_after=collapse_after,
    )


def render_summary(
    published: Mapping[str, Any],
    *,
    templates_dir: Path | None = None,
    max_chars: int = DEFAULT_SUMMARY_LIMIT,
    artifact_url: str | None = None,
) -> str:
    """Render a GitHub-friendly summary that never drops counts/gate under truncation."""
    header = published.get("header", {})
    counts = published.get("counts", {})
    gate = str(header.get("gate_status", "unknown")).upper()
    artifact = artifact_url or header.get("artifact_name") or "normocontrol-report"
    body = render_markdown(published, templates_dir=templates_dir, collapse_after=5)
    if len(body) <= max_chars:
        return body

    # Truncate finding details but keep the mandatory header/counts block.
    prefix = "\n".join(
        [
            GITHUB_SUMMARY_MARKER,
            f"## NORMACTRL: {gate}",
            "",
            "| Category | Count |",
            "|---|---:|",
            f"| Formal errors | {counts.get('formal_errors', 0)} |",
            f"| Warnings | {counts.get('warnings', 0)} |",
            f"| LLM advisory | {counts.get('llm_advisory', 0)} |",
            f"| Unverifiable | {counts.get('unverifiable', 0)} |",
            f"| Blocking unverifiable | {counts.get('blocking_unverifiable', 0)} |",
            f"| Approvals required | {counts.get('approvals_required', 0)} |",
            "",
            f"Gate: `{gate}` · exit `{published.get('exit_code', 0)}`",
            f"Artifact: `{artifact}`",
            "",
            "<details><summary>Truncated findings</summary>",
            "",
            "_Report exceeded GitHub comment size limit; "
            "full details are in the workflow artifact._",
            "",
            "</details>",
            "",
        ]
    )
    if len(prefix) > max_chars:
        return prefix[: max_chars - 20] + "\n\n...[TRUNCATED]\n"
    return prefix
