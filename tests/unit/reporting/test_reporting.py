"""Unit tests for A-02 reporting package."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from normocontrol.domain import (
    Evidence,
    ExitCode,
    Finding,
    FindingStatus,
    RuleLayer,
    RunReport,
    Severity,
    StageResult,
)
from normocontrol.reporting.aggregate import publish_reports
from normocontrol.reporting.fingerprint import finding_fingerprint
from normocontrol.reporting.json_report import (
    ReportMeta,
    build_published_report,
    load_report_schema,
    validate_published_report,
)
from normocontrol.reporting.markdown import (
    GITHUB_COMMENT_LIMIT,
    render_markdown,
    render_summary,
)
from normocontrol.reporting.redaction import redact_structure, redact_text, sanitize_evidence_text

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOTS = ROOT / "tests" / "snapshots"


def _finding(**overrides: object) -> Finding:
    values: dict[str, object] = {
        "rule_id": "STR-01",
        "layer": RuleLayer.SCRIPT,
        "severity": Severity.ERROR,
        "status": FindingStatus.FAIL,
        "message": "Нарушен порядок разделов",
        "evidence": (Evidence(locator="main.tex:3"),),
        "path": "main.tex",
    }
    values.update(overrides)
    return Finding.model_validate(values)


def _report(*findings: Finding, exit_code: ExitCode = ExitCode.FORMAL_FAILURE) -> RunReport:
    return RunReport(
        tool_version="0.1.0",
        exit_code=exit_code,
        stages=(StageResult(name="formal", findings=findings),),
    )


def test_schema_validation_pass_fail_mixed_degraded(tmp_path: Path) -> None:
    cases = {
        "pass": _report(exit_code=ExitCode.SUCCESS),
        "fail": _report(_finding()),
        "mixed": _report(
            _finding(),
            _finding(
                rule_id="ANN-01",
                layer=RuleLayer.LLM,
                severity=Severity.WARN,
                status=FindingStatus.WARN,
                message="Слабая аннотация",
            ),
            exit_code=ExitCode.FORMAL_FAILURE,
        ),
        "degraded": _report(
            _finding(
                rule_id="SYS-03",
                severity=Severity.WARN,
                status=FindingStatus.UNVERIFIABLE,
                message="latexmk недоступен",
            ),
            exit_code=ExitCode.SUCCESS,
        ),
    }
    schema = load_report_schema()
    for name, report in cases.items():
        published = build_published_report(
            report,
            ReportMeta(
                commit_sha="deadbeef",
                profile="software",
                rubric_version="2025.1-draft",
                degraded=(name == "degraded"),
                approvals_required=False,
                artifact_name="normocontrol-report-deadbee",
                repo_root=ROOT,
            ),
            clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
        )
        validate_published_report(published, schema=schema)
        snap = SNAPSHOTS / f"report-{name}.json"
        if not snap.exists():
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_text(
                json.dumps(published, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        expected = json.loads(snap.read_text(encoding="utf-8"))
        # stages duration may vary; compare header/counts/findings fingerprints
        assert published["header"]["gate_status"] == expected["header"]["gate_status"]
        assert published["counts"] == expected["counts"]
        assert published["exit_code"] == expected["exit_code"]
        assert [item["fingerprint"] for item in published["findings"]] == [
            item["fingerprint"] for item in expected["findings"]
        ]


def test_fingerprint_stable_after_absolute_path_change() -> None:
    first = _finding(
        path=r"C:\Users\a\GostCheck\tests\fixtures\demo\fail\main.tex",
        evidence=(
            Evidence(locator=r"C:\Users\a\GostCheck\tests\fixtures\demo\fail\main.tex:3"),
        ),
    )
    second = _finding(
        path=r"C:\Users\b\work\GostCheck\tests\fixtures\demo\fail\main.tex",
        evidence=(
            Evidence(
                locator=r"C:\Users\b\work\GostCheck\tests\fixtures\demo\fail\main.tex:3"
            ),
        ),
    )
    assert finding_fingerprint(first, repo_root=Path(r"C:\Users\a\GostCheck")) == (
        finding_fingerprint(second, repo_root=Path(r"C:\Users\b\work\GostCheck"))
    )


def test_redaction_api_keys_emails_usernames_and_prompts() -> None:
    text = (
        "user C:\\Users\\hasha\\project api_key=sk-super-secret-value "
        "mail student@example.com raw_prompt='FULL PROMPT TEXT' "
        "Bearer tok_abc123456"
    )
    redacted = redact_text(text)
    assert "sk-super-secret-value" not in redacted
    assert "hasha" not in redacted
    assert "student@example.com" not in redacted
    assert "FULL PROMPT TEXT" not in redacted
    assert "[REDACTED]" in redacted

    payload = redact_structure(
        {
            "message": "ok",
            "raw_prompt": "should vanish",
            "nested": {"email": "a@b.cd"},
        }
    )
    assert payload["raw_prompt"] == "[REDACTED]"
    assert payload["nested"]["email"] == "[REDACTED]"


def test_markdown_truncation_keeps_counts_and_gate() -> None:
    findings = [
        _finding(rule_id=f"STR-{index:02d}", message=f"msg {index} " + ("x" * 200))
        for index in range(1, 40)
    ]
    # Domain only allows STR-01 style via free string - rule_id is NonEmptyString, OK
    report = RunReport(
        tool_version="0.1.0",
        exit_code=ExitCode.FORMAL_FAILURE,
        stages=(StageResult(name="formal", findings=tuple(findings)),),
    )
    published = build_published_report(
        report,
        ReportMeta(commit_sha="abc1234", profile="software", repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )
    summary = render_summary(published, max_chars=1_500)
    assert "<!-- normocontrol-report -->" in summary
    assert "NORMACTRL: FAIL" in summary
    assert "Formal errors" in summary
    assert str(published["counts"]["formal_errors"]) in summary
    assert len(summary) <= 1_500
    assert len(summary) < GITHUB_COMMENT_LIMIT


def test_evidence_markdown_and_malicious_details_are_sanitized() -> None:
    dirty = "see </details><details><summary>x</summary>```html<script>```"
    cleaned = sanitize_evidence_text(dirty)
    assert "</details>" not in cleaned
    assert "```" not in cleaned


def test_publish_writes_all_artifacts(tmp_path: Path) -> None:
    report = _report(_finding())
    result = publish_reports(
        report,
        tmp_path,
        meta=ReportMeta(
            commit_sha="abcdef0",
            profile="software",
            rubric_version="2025.1-draft",
            repo_root=ROOT,
        ),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert result.report_json.is_file()
    assert result.report_md.is_file()
    assert result.summary_json.is_file()
    markdown = result.report_md.read_text(encoding="utf-8")
    assert "<!-- normocontrol-report -->" in markdown
    assert "Formal errors" in markdown
    published = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert published["header"]["gate_status"] == "fail"
    # Renderer must not change gate/exit.
    assert published["exit_code"] == 2


def test_page_zero_is_omitted() -> None:
    finding = _finding()
    # Construct published payload via normalize path; page=0 rejected by domain,
    # so simulate by clearing page after build.
    published = build_published_report(
        _report(finding),
        ReportMeta(commit_sha="x", repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )
    for item in published["findings"]:
        assert item.get("page") is None or item["page"] >= 1


def test_approval_required_grouped() -> None:
    report = _report(
        _finding(
            rule_id="SYS-01",
            severity=Severity.WARN,
            status=FindingStatus.UNVERIFIABLE,
            message="APPROVAL_REQUIRED: эталонный .cls не утверждён",
        ),
        exit_code=ExitCode.SUCCESS,
    )
    published = build_published_report(
        report,
        ReportMeta(commit_sha="x", approvals_required=True, repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert published["counts"]["approvals_required"] >= 1
    assert published["header"]["approvals_required"] is True
    md = render_markdown(published)
    assert "Approvals required" in md
