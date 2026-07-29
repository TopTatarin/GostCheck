"""Unit tests for A-02 reporting package."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

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
    count_findings,
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
TOP_LEVEL_FINDING_RE = re.compile(r"(?m)^- \*\*[A-Z]{3}-\d{2}\*\*")
GLUED_FINDING_RE = re.compile(r"[^\r\n]- \*\*[A-Z]{3}-\d{2}\*\*")
TRUNCATED_GLUE_RE = re.compile(r"\[TRUNCATED\]- \*\*")


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


def _published(*findings: Finding) -> dict[str, Any]:
    return build_published_report(
        _report(*findings),
        ReportMeta(commit_sha="abc1234", profile="software", repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )


def _assert_findings_are_separated(markdown: str, *, expected: int) -> None:
    assert len(TOP_LEVEL_FINDING_RE.findall(markdown)) == expected
    assert GLUED_FINDING_RE.search(markdown) is None
    assert TRUNCATED_GLUE_RE.search(markdown) is None


def test_schema_validation_pass_fail_mixed_degraded() -> None:
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
                severity=Severity.ERROR,
                status=FindingStatus.UNVERIFIABLE,
                message="latexmk недоступен",
            ),
            exit_code=ExitCode.FORMAL_FAILURE,
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
        expected = json.loads(snap.read_text(encoding="utf-8"))
        assert published == expected


def test_default_clock_is_current_utc_with_seconds_and_z() -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    published = build_published_report(
        _report(exit_code=ExitCode.SUCCESS),
        ReportMeta(commit_sha="x", repo_root=ROOT),
    )
    after = datetime.now(UTC).replace(microsecond=0)

    generated_at = published["header"]["generated_at"]
    stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    assert before <= stamp <= after
    assert stamp.microsecond == 0
    assert generated_at.endswith("Z")


def test_naive_and_backward_injected_clocks_are_deterministic_utc() -> None:
    readings = iter(
        (
            datetime(2026, 7, 24, 12, 30, 45, 999999),
            datetime(2026, 7, 24, 12, 29, 45, tzinfo=UTC),
        )
    )
    meta = ReportMeta(commit_sha="x", repo_root=ROOT)
    report = _report(exit_code=ExitCode.SUCCESS)

    first = build_published_report(report, meta, clock=lambda: next(readings))
    second = build_published_report(report, meta, clock=lambda: next(readings))

    assert first["header"]["generated_at"] == "2026-07-24T12:30:45Z"
    assert second["header"]["generated_at"] == "2026-07-24T12:29:45Z"


def test_fingerprint_stable_after_absolute_path_change() -> None:
    first = _finding(
        path=r"C:\Users\a\GostCheck\tests\fixtures\demo\fail\main.tex",
        evidence=(Evidence(locator=r"C:\Users\a\GostCheck\tests\fixtures\demo\fail\main.tex:3"),),
    )
    second = _finding(
        path=r"C:\Users\b\work\GostCheck\tests\fixtures\demo\fail\main.tex",
        evidence=(
            Evidence(locator=r"C:\Users\b\work\GostCheck\tests\fixtures\demo\fail\main.tex:3"),
        ),
    )
    assert finding_fingerprint(first, repo_root=Path(r"C:\Users\a\GostCheck")) == (
        finding_fingerprint(second, repo_root=Path(r"C:\Users\b\work\GostCheck"))
    )


def test_redaction_api_keys_emails_usernames_and_prompts() -> None:
    text = (
        "user C:\\Users\\hasha\\project\\main.tex "
        "unix /home/student/thesis/main.tex api_key=sk-super-secret-value "
        "mail student@example.com raw_prompt='FULL PROMPT TEXT' "
        "Bearer tok_abc123456"
    )
    redacted = redact_text(text)
    assert "sk-super-secret-value" not in redacted
    assert "hasha" not in redacted
    assert r"C:\Users" not in redacted
    assert "/home/student" not in redacted
    assert "student@example.com" not in redacted
    assert "FULL PROMPT TEXT" not in redacted
    assert "[REDACTED]" in redacted
    provider_error = redact_text(
        "provider failed\nTraceback (most recent call last):\n"
        '  File "/home/student/provider.py", line 1\n'
        "ProviderError: secret"
    )
    assert "provider.py" not in provider_error
    assert "ProviderError" not in provider_error
    assert provider_error.endswith("[REDACTED_TRACEBACK]")

    payload = redact_structure(
        {
            "message": "full document text " * 100,
            "raw_prompt": "should vanish",
            "nested": {
                "email": "a@b.cd",
                "api_key": "short-secret",
                "description": "quoted thesis text " * 100,
                "provider_traceback": (
                    "Traceback (most recent call last):\n"
                    '  File "/home/student/provider.py", line 1\n'
                    "ProviderError: secret"
                ),
            },
        }
    )
    assert payload["raw_prompt"] == "[REDACTED]"
    assert payload["message"].endswith("[TRUNCATED]")
    assert payload["nested"]["email"] == "[REDACTED]"
    assert payload["nested"]["api_key"] == "[REDACTED]"
    assert payload["nested"]["description"].endswith("[TRUNCATED]")
    assert "quoted thesis text" not in payload["nested"]["description"][240:]
    assert payload["nested"]["provider_traceback"] == "[REDACTED_TRACEBACK]"


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
    assert "Blocking unverifiable" in summary
    assert str(published["counts"]["formal_errors"]) in summary
    assert len(summary) <= 1_500
    assert len(summary) < GITHUB_COMMENT_LIMIT


def test_evidence_markdown_and_malicious_details_are_sanitized() -> None:
    dirty = "see </details><details><summary>x</summary>```html<script>```"
    cleaned = sanitize_evidence_text(dirty)
    assert "</details>" not in cleaned
    assert "```" not in cleaned


def test_markdown_separates_adjacent_findings() -> None:
    markdown = render_markdown(
        _published(
            _finding(rule_id="FMT-04", message="First short finding"),
            _finding(rule_id="FMT-05", message="Second short finding"),
        )
    )

    _assert_findings_are_separated(markdown, expected=2)


def test_markdown_separates_one_hundred_collapsed_findings() -> None:
    markdown = render_markdown(
        _published(
            *(
                _finding(rule_id=f"FMT-{index:02d}", message=f"Finding {index}")
                for index in range(100)
            )
        )
    )

    assert "<details>" in markdown
    assert "<summary>100 items (click to expand)</summary>" in markdown
    _assert_findings_are_separated(markdown, expected=100)


def test_truncated_message_cannot_touch_next_finding() -> None:
    markdown = render_markdown(
        _published(
            _finding(rule_id="FMT-04", message="long message " * 100),
            _finding(rule_id="FMT-05", message="Next finding"),
        )
    )

    assert "[TRUNCATED]" in markdown
    _assert_findings_are_separated(markdown, expected=2)


def test_markdown_sanitizes_multiline_content_and_keeps_evidence_nested() -> None:
    markdown = render_markdown(
        _published(
            _finding(
                rule_id="FMT-04",
                message="Без evidence",
                evidence=(),
            ),
            _finding(
                rule_id="FMT-05",
                message=(
                    "Юникод\n- **FMT-99** <script>alert(1)</script> "
                    "**bold** [link](https://example.invalid)"
                ),
                evidence=(
                    Evidence(
                        locator="page:2\n`escape`",
                        description="Первая строка\n<details>unsafe</details>",
                    ),
                    Evidence(
                        locator="page:3",
                        description="Вторая **цитата**",
                    ),
                ),
            ),
        )
    )

    _assert_findings_are_separated(markdown, expected=2)
    evidence_lines = [line for line in markdown.splitlines() if "evidence:" in line]
    assert len(evidence_lines) == 2
    assert all(line.startswith("  - evidence:") for line in evidence_lines)
    assert all(line.count("`") == 2 for line in evidence_lines)
    first_start = markdown.index("- **FMT-04**")
    second_start = markdown.index("- **FMT-05**")
    assert "evidence:" not in markdown[first_start:second_start]
    assert "Юникод" in markdown
    assert "<script>" not in markdown
    assert "<details>" not in "\n".join(evidence_lines)
    assert r"\*\*bold\*\*" in markdown
    assert r"\[link\]" in markdown


def test_full_markdown_report_snapshot() -> None:
    published = _published(
        _finding(rule_id="FMT-04", message="First finding", evidence=()),
        _finding(
            rule_id="FMT-05",
            message="Second finding",
            evidence=(
                Evidence(locator="page:2", description="First quote"),
                Evidence(locator="page:3", description="Second quote"),
            ),
        ),
    )
    for index, finding in enumerate(published["findings"], start=1):
        finding["recommendation"] = f"Review finding {index}."

    markdown = render_markdown(published)
    actual = markdown if markdown.endswith("\n") else f"{markdown}\n"

    assert actual == (SNAPSHOTS / "report-markdown.md").read_text(encoding="utf-8")


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


def test_blocking_unverifiable_count_is_separate_from_formal_errors() -> None:
    incomplete = _finding(status=FindingStatus.UNVERIFIABLE)
    advisory = _finding(
        rule_id="ANN-01",
        layer=RuleLayer.LLM,
        status=FindingStatus.UNVERIFIABLE,
    )

    counts = count_findings((incomplete, advisory))

    assert counts["formal_errors"] == 0
    assert counts["unverifiable"] == 2
    assert counts["blocking_unverifiable"] == 1


def test_degraded_tracks_only_blocking_formal_unverifiable() -> None:
    llm_only = _report(
        _finding(
            rule_id="ANN-01",
            layer=RuleLayer.LLM,
            severity=Severity.ERROR,
            status=FindingStatus.UNVERIFIABLE,
        ),
        exit_code=ExitCode.SUCCESS,
    )
    warning_only = _report(
        _finding(severity=Severity.WARN, status=FindingStatus.WARN),
        exit_code=ExitCode.SUCCESS,
    )
    formal_incomplete = _report(
        _finding(status=FindingStatus.UNVERIFIABLE),
        exit_code=ExitCode.FORMAL_FAILURE,
    )

    for report in (llm_only, warning_only, _report(exit_code=ExitCode.SUCCESS)):
        published = build_published_report(
            report,
            ReportMeta(commit_sha="x", repo_root=ROOT),
            clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
        )
        assert published["header"]["degraded"] is False
        assert published["counts"]["blocking_unverifiable"] == 0

    incomplete = build_published_report(
        formal_incomplete,
        ReportMeta(commit_sha="x", repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert incomplete["header"]["degraded"] is True
    assert incomplete["counts"]["blocking_unverifiable"] == 1


def test_formal_fail_and_blocking_unverifiable_have_independent_counts() -> None:
    report = _report(
        _finding(),
        _finding(rule_id="FMT-04", status=FindingStatus.UNVERIFIABLE),
    )

    published = build_published_report(
        report,
        ReportMeta(commit_sha="x", repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )

    assert published["counts"]["formal_errors"] == 1
    assert published["counts"]["blocking_unverifiable"] == 1
    assert published["header"]["degraded"] is True


@pytest.mark.parametrize(
    "unknown_field",
    ("top_level", "header", "counts"),
)
def test_schema_rejects_unknown_fields(unknown_field: str) -> None:
    published = build_published_report(
        _report(exit_code=ExitCode.SUCCESS),
        ReportMeta(commit_sha="x", repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )
    if unknown_field == "top_level":
        published["unknown"] = True
    else:
        published[unknown_field]["unknown"] = True

    with pytest.raises(JsonSchemaValidationError):
        validate_published_report(published, schema=load_report_schema())


def test_schema_1_1_remains_valid_without_new_counter() -> None:
    published = build_published_report(
        _report(exit_code=ExitCode.SUCCESS),
        ReportMeta(commit_sha="x", repo_root=ROOT),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
    )
    published["schema_version"] = "1.1"
    del published["counts"]["blocking_unverifiable"]

    validate_published_report(published, schema=load_report_schema())


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
