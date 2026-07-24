"""Unit tests for scripts/ci_comment.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import scripts.ci_comment as ci_comment


def test_escape_untrusted_content_and_keeps_marker() -> None:
    dirty = "</details><script>alert(1)</script>```rm -rf```"
    cleaned = ci_comment.escape_untrusted(dirty)
    assert ci_comment.MARKER in cleaned
    assert "</details>" not in cleaned
    assert "<script" not in cleaned
    assert "```" not in cleaned


def test_upsert_updates_existing_marker_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, url: str, token: str, body: dict[str, Any] | None = None):
        del token, body
        calls.append((method, url))
        if method == "GET":
            return 200, [{"id": 42, "body": f"{ci_comment.MARKER}\nold"}]
        if method == "PATCH":
            return 200, {"id": 42, "body": "updated"}
        raise AssertionError(f"unexpected {method}")

    monkeypatch.setattr(ci_comment, "_api_request", fake_api)
    result = ci_comment.upsert_comment(
        repo="owner/repo",
        pr_number=7,
        token="token",
        body=f"{ci_comment.MARKER}\nhello",
    )
    assert result.status == "updated"
    assert result.comment_id == 42
    assert any(method == "PATCH" for method, _ in calls)


def test_upsert_creates_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_api(method: str, url: str, token: str, body: dict[str, Any] | None = None):
        del url, token, body
        if method == "GET":
            return 200, [{"id": 1, "body": "unrelated"}]
        if method == "POST":
            return 201, {"id": 99}
        raise AssertionError(method)

    monkeypatch.setattr(ci_comment, "_api_request", fake_api)
    result = ci_comment.upsert_comment(
        repo="owner/repo",
        pr_number=7,
        token="token",
        body="new body",
    )
    assert result.status == "created"
    assert result.comment_id == 99


@pytest.mark.parametrize("status", [403, 422, 429])
def test_upsert_neutral_on_blocked_write(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def fake_api(method: str, url: str, token: str, body: dict[str, Any] | None = None):
        del url, token, body
        if method == "GET":
            return 200, []
        return status, {"message": "nope"}

    monkeypatch.setattr(ci_comment, "_api_request", fake_api)
    result = ci_comment.upsert_comment(
        repo="owner/repo",
        pr_number=3,
        token="token",
        body="x",
    )
    assert result.status == "neutral"


def test_main_missing_token_is_neutral(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps({"markdown": f"{ci_comment.MARKER}\nok", "counts": {}}),
        encoding="utf-8",
    )
    code = ci_comment.main(
        [
            "--summary",
            str(summary),
            "--repo",
            "o/r",
            "--pr",
            "1",
            "--token",
            "",
            "--neutral",
        ]
    )
    assert code == 0


def test_main_missing_artifact_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ci_comment,
        "upsert_comment",
        lambda **kwargs: ci_comment.CommentResult(status="created", comment_id=1),
    )
    code = ci_comment.main(
        [
            "--missing-artifact",
            "--neutral",
            "--repo",
            "o/r",
            "--pr",
            "9",
            "--token",
            "t",
        ]
    )
    assert code == 0


def test_parse_pr_number_from_event(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 15}}), encoding="utf-8")
    assert ci_comment.parse_pr_number(event) == 15
