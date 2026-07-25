#!/usr/bin/env python3
"""Create or update a single PR comment with the normocontrol summary marker."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

MARKER = "<!-- normocontrol-report -->"
GITHUB_API = "https://api.github.com"
MAX_COMMENT_CHARS = 65_000


@dataclass(frozen=True, slots=True)
class CommentResult:
    """Outcome of a comment create/update attempt."""

    status: str
    comment_id: int | None = None
    detail: str = ""


def escape_untrusted(text: str) -> str:
    """Neutralize HTML/script payloads while keeping Markdown readable."""
    cleaned = text.replace("\x00", "")
    cleaned = cleaned.replace("</details>", "<\\/details>")
    cleaned = cleaned.replace("<script", "&lt;script")
    cleaned = cleaned.replace("```", "'''")
    if len(cleaned) > MAX_COMMENT_CHARS:
        head = cleaned[: MAX_COMMENT_CHARS - 80]
        cleaned = f"{head}\n\n...[TRUNCATED for GitHub comment limit]\n{MARKER}\n"
    if MARKER not in cleaned:
        cleaned = f"{MARKER}\n{cleaned}"
    return cleaned


def load_markdown_from_summary(path: Path) -> str:
    """Read markdown body from summary.json or fall back to raw Markdown file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("markdown"), str):
        return payload["markdown"]
    raise ValueError(f"summary file missing markdown field: {path}")


def parse_pr_number(event_path: Path | None) -> int | None:
    """Extract pull request number from GitHub event payload when present."""
    if event_path is None or not event_path.is_file():
        return None
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    pr = payload.get("pull_request")
    if isinstance(pr, dict) and isinstance(pr.get("number"), int):
        return pr["number"]
    number = payload.get("number")
    return number if isinstance(number, int) else None


def _api_request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "gostcheck-ci-comment",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            parsed: Any = json.loads(raw) if raw else None
            return int(response.status), parsed
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"message": str(exc)}
        except json.JSONDecodeError:
            parsed = {"message": raw or str(exc)}
        return int(exc.code), parsed


def list_comments(repo: str, pr_number: int, token: str) -> list[dict[str, Any]]:
    """Return issue comments for a pull request."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    status, payload = _api_request("GET", url, token)
    if status == 403:
        raise PermissionError("GITHUB_TOKEN cannot read pull request comments")
    if status >= 400:
        raise RuntimeError(f"list comments failed: HTTP {status}: {payload}")
    if not isinstance(payload, list):
        raise RuntimeError("unexpected comments payload")
    return [item for item in payload if isinstance(item, dict)]


def find_marker_comment(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the first bot comment that contains the stable marker."""
    for comment in comments:
        body = comment.get("body")
        if isinstance(body, str) and MARKER in body:
            return comment
    return None


def upsert_comment(
    *,
    repo: str,
    pr_number: int,
    token: str,
    body: str,
) -> CommentResult:
    """Create or update the single marker comment for a PR."""
    safe_body = escape_untrusted(body)
    comments = list_comments(repo, pr_number, token)
    existing = find_marker_comment(comments)
    if existing is not None:
        comment_id = existing.get("id")
        if not isinstance(comment_id, int):
            raise RuntimeError("marker comment missing integer id")
        url = f"{GITHUB_API}/repos/{repo}/issues/comments/{comment_id}"
        status, payload = _api_request("PATCH", url, token, {"body": safe_body})
        if status in {403, 422}:
            return CommentResult(status="neutral", detail=f"update blocked HTTP {status}")
        if status == 429:
            return CommentResult(status="neutral", detail="rate limited")
        if status >= 400:
            raise RuntimeError(f"update comment failed: HTTP {status}: {payload}")
        return CommentResult(status="updated", comment_id=comment_id)
    url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    status, payload = _api_request("POST", url, token, {"body": safe_body})
    if status in {403, 422}:
        return CommentResult(status="neutral", detail=f"create blocked HTTP {status}")
    if status == 429:
        return CommentResult(status="neutral", detail="rate limited")
    if status >= 400:
        raise RuntimeError(f"create comment failed: HTTP {status}: {payload}")
    comment_id = payload.get("id") if isinstance(payload, dict) else None
    return CommentResult(
        status="created",
        comment_id=comment_id if isinstance(comment_id, int) else None,
    )


def build_neutral_missing_artifact_body() -> str:
    """Body used when formal artifacts are unavailable."""
    return (
        f"{MARKER}\n"
        "## NORMACTRL: NEUTRAL\n\n"
        "Formal report artifact is missing or incomplete. "
        "The publish job stays non-blocking; inspect the formal-gate logs.\n"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for GitHub Actions publish-report job."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, help="Path to summary.json")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument(
        "--event-path",
        type=Path,
        default=Path(os.environ["GITHUB_EVENT_PATH"])
        if os.environ.get("GITHUB_EVENT_PATH")
        else None,
    )
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--missing-artifact", action="store_true")
    parser.add_argument(
        "--neutral",
        action="store_true",
        help="Exit 0 even when the token cannot write comments (fork PR).",
    )
    args = parser.parse_args(argv)

    if not args.repo:
        print("ERROR repository is required", file=sys.stderr)
        return 3
    pr_number = args.pr if args.pr is not None else parse_pr_number(args.event_path)
    if pr_number is None:
        print("ERROR pull request number is required", file=sys.stderr)
        return 3

    if not args.token:
        print("WARNING GITHUB_TOKEN missing; publish stays neutral")
        return 0

    if args.missing_artifact:
        body = build_neutral_missing_artifact_body()
    elif args.summary is None:
        print("ERROR --summary is required unless --missing-artifact", file=sys.stderr)
        return 3
    else:
        try:
            body = load_markdown_from_summary(args.summary)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR cannot read summary: {exc}", file=sys.stderr)
            return 3

    try:
        result = upsert_comment(
            repo=args.repo,
            pr_number=pr_number,
            token=args.token,
            body=body,
        )
    except PermissionError as exc:
        print(f"WARNING {exc}; publish neutral")
        return 0
    except RuntimeError as exc:
        if args.neutral:
            print(f"WARNING {exc}; publish neutral")
            return 0
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    print(f"status={result.status} comment_id={result.comment_id} detail={result.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
