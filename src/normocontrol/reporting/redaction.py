"""Redaction helpers for published reports (secrets, emails, usernames)."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_API_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AQVN[A-Za-z0-9_-]{8,})\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*")
_KEY_ASSIGN = re.compile(
    r"(?i)(\b(?:api[_-]?key|token|secret|password|authorization|llm_api_key)\b\s*[:=]\s*)"
    r"(['\"]?)[^\s,;'\"\)\}\]]+"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_WIN_USER = re.compile(r"(?i)\b([A-Za-z]:\\Users\\)([^\\/]+)(\\?)")
_POSIX_USER = re.compile(r"(?i)(/home/)([^/]+)(/?)")
_PROMPT_BLOCK = re.compile(
    r"(?is)(\b(?:raw_prompt|prompt_text|system_prompt|llm_prompt)\b\s*[:=]\s*)"
    r"(['\"]).*?\2"
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def redact_text(value: str, *, keep_short_quotes: bool = True) -> str:
    """Redact credentials and usernames while preserving short evidence quotes."""
    text = _CONTROL_CHARS.sub("", value)
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _KEY_ASSIGN.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _EMAIL.sub(REDACTED, text)
    text = _WIN_USER.sub(rf"\1{REDACTED}\3", text)
    text = _POSIX_USER.sub(rf"\1{REDACTED}\3", text)
    text = _PROMPT_BLOCK.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    if keep_short_quotes:
        # Avoid wiping a short thesis fragment that only resembles a secret token.
        return text
    return text


def redact_structure(value: Any) -> Any:
    """Recursively redact strings inside JSON-compatible structures."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_structure(item) for item in value]
    if isinstance(value, tuple):
        return [redact_structure(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_l = str(key).casefold()
            if key_l in {"raw_prompt", "prompt_text", "system_prompt", "llm_prompt"}:
                result[str(key)] = REDACTED
            else:
                result[str(key)] = redact_structure(item)
        return result
    return value


def sanitize_evidence_text(value: str) -> str:
    """Escape markdown/HTML hazards in evidence shown in Markdown reports."""
    cleaned = _CONTROL_CHARS.sub("", value)
    cleaned = cleaned.replace("```", "'''")
    cleaned = cleaned.replace("</details>", "<\\/details>")
    cleaned = cleaned.replace("<details", "&lt;details")
    return redact_text(cleaned)
