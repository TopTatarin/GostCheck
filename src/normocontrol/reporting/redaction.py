"""Redaction helpers for published reports (secrets, emails, usernames)."""

from __future__ import annotations

import html
import re
from typing import Any

REDACTED = "[REDACTED]"
REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_TRACEBACK = "[REDACTED_TRACEBACK]"
TRUNCATED_TEXT = "[TRUNCATED]"
MAX_EVIDENCE_CHARS = 240

_API_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AQVN[A-Za-z0-9_-]{8,})\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*")
_KEY_ASSIGN = re.compile(
    r"(?i)(\b(?:api[_-]?key|token|secret|password|authorization|llm_api_key)\b\s*[:=]\s*)"
    r"(['\"]?)[^\s,;'\"\)\}\]]+"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_WIN_ABSOLUTE_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:[A-Z]:[\\/]|\\\\[^\\/\s]+[\\/])"
    r"[^ \t\r\n,;:'\"<>|?*]+"
)
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![\w:/])/(?:[^/ \t\r\n,;:'\"<>{}\[\]()]+/)*"
    r"[^/ \t\r\n,;:'\"<>{}\[\]()]+"
)
_TILDE_HOME_PATH = re.compile(r"(?<![A-Za-z0-9_])~/(?:[^ \t\r\n,;:'\"<>{}\[\]()]+)")
_PROMPT_BLOCK = re.compile(
    r"(?is)(\b(?:raw_prompt|prompt_text|system_prompt|llm_prompt)\b\s*[:=]\s*)"
    r"(['\"]).*?\2"
)
_TRACEBACK_START = re.compile(r"(?im)^Traceback \(most recent call last\):")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MARKDOWN_INLINE = re.compile(r"([\\`*])")
_MARKDOWN_LINK = re.compile(r"(!?)\[([^\]\r\n]*)\]\(")
_MARKDOWN_UNDERSCORE = re.compile(r"(?<!\w)_(?=\S)|(?<=\S)_(?!\w)")
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "llm_api_key",
        "password",
        "secret",
        "token",
    }
)
_TRACEBACK_KEYS = frozenset(
    {
        "provider_traceback",
        "stack_trace",
        "traceback",
    }
)
_PROMPT_KEYS = frozenset({"raw_prompt", "prompt_text", "system_prompt", "llm_prompt"})
_PUBLIC_TEXT_KEYS = frozenset({"description", "message", "quote"})


def _truncate_public_text(value: str) -> str:
    if len(value) <= MAX_EVIDENCE_CHARS:
        return value
    return f"{value[:MAX_EVIDENCE_CHARS].rstrip()}… {TRUNCATED_TEXT}"


def redact_text(value: str, *, keep_short_quotes: bool = True) -> str:
    """Redact credentials and usernames while preserving short evidence quotes."""
    text = _CONTROL_CHARS.sub("", value)
    text = _KEY_ASSIGN.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _EMAIL.sub(REDACTED, text)
    text = _WIN_ABSOLUTE_PATH.sub(REDACTED_PATH, text)
    text = _POSIX_ABSOLUTE_PATH.sub(REDACTED_PATH, text)
    text = _TILDE_HOME_PATH.sub(REDACTED_PATH, text)
    text = _PROMPT_BLOCK.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    traceback = _TRACEBACK_START.search(text)
    if traceback is not None:
        prefix = text[: traceback.start()].rstrip()
        text = f"{prefix} {REDACTED_TRACEBACK}".lstrip()
    if keep_short_quotes:
        # Avoid wiping a short thesis fragment that only resembles a secret token.
        return text
    return text


def redact_structure(value: Any) -> Any:
    """Recursively redact strings inside JSON-compatible structures."""
    return _redact_structure(value, key=None)


def _redact_structure(value: Any, *, key: str | None) -> Any:
    if isinstance(value, str):
        redacted = redact_text(value)
        return _truncate_public_text(redacted) if key in _PUBLIC_TEXT_KEYS else redacted
    if isinstance(value, list):
        return [_redact_structure(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_redact_structure(item, key=key) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key_text = str(raw_key)
            key_l = key_text.casefold()
            if key_l in _TRACEBACK_KEYS:
                result[key_text] = REDACTED_TRACEBACK
            elif key_l in _PROMPT_KEYS or key_l in _SENSITIVE_KEYS:
                result[key_text] = REDACTED
            else:
                result[key_text] = _redact_structure(item, key=key_l)
        return result
    return value


def sanitize_evidence_text(value: str) -> str:
    """Escape markdown/HTML hazards in evidence shown in Markdown reports."""
    cleaned = " ".join(_CONTROL_CHARS.sub("", value).split())
    cleaned = _truncate_public_text(redact_text(cleaned))
    was_truncated = cleaned.endswith(TRUNCATED_TEXT)
    if was_truncated:
        cleaned = cleaned[: -len(TRUNCATED_TEXT)]
    cleaned = html.escape(cleaned, quote=False)
    cleaned = _MARKDOWN_INLINE.sub(r"\\\1", cleaned)
    cleaned = _MARKDOWN_LINK.sub(r"\1\\[\2\\](", cleaned)
    cleaned = _MARKDOWN_UNDERSCORE.sub(r"\\_", cleaned)
    return f"{cleaned}{TRUNCATED_TEXT if was_truncated else ''}"
