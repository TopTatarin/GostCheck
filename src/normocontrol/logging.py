"""Safe stderr logging helpers."""

from __future__ import annotations

import logging
import re
import sys
from types import TracebackType
from typing import Final

LOG_FORMAT: Final = "%(levelname)s %(name)s: %(message)s"
REDACTED: Final = "[REDACTED]"
MAX_LOG_MESSAGE: Final = 500

_SECRET_PATTERNS: Final = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*"),
    re.compile(
        r"(?i)(\b(?:api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*)"
        r"(['\"]?)[^\s,;'\"\)\}\]]+(['\"]?)"
    ),
    re.compile(
        r"(?is)(\b(?:document_text|thesis_text|vkr_text)\b\s*[:=]\s*)"
        r"(['\"]).*?\2"
    ),
)


def redact_text(value: object, max_length: int | None = MAX_LOG_MESSAGE) -> str:
    """Return a bounded string with credentials and document payloads removed."""
    text = str(value)
    text = _SECRET_PATTERNS[0].sub(REDACTED, text)
    text = _SECRET_PATTERNS[1].sub(f"Bearer {REDACTED}", text)
    text = _SECRET_PATTERNS[2].sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _SECRET_PATTERNS[3].sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    if max_length is not None and len(text) > max_length:
        text = f"{text[:max_length]}...[TRUNCATED]"
    return text


class SecretRedactionFilter(logging.Filter):
    """Redact unsafe data before it reaches any logging handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        return True


class RedactingFormatter(logging.Formatter):
    """Redact exception tracebacks as a second line of defence."""

    def formatException(
        self,
        ei: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None],
    ) -> str:
        return redact_text(super().formatException(ei), max_length=None)


def configure_logging(verbose: bool = False) -> None:
    """Configure stderr logging without secrets or document content."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=LOG_FORMAT,
        stream=sys.stderr,
        force=True,
    )
    formatter = RedactingFormatter(LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretRedactionFilter())
        handler.setFormatter(formatter)
