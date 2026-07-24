"""LaTeX citation extraction for bibliography and review rules."""

from __future__ import annotations

import re

from normocontrol.rules.latex_symbols import prepare_body

_CITE_COMMAND_RE = re.compile(
    r"\\(?:cite|parencite|textcite|autocite|supercite|footcite|footcitet|"
    r"footcitep|footcitetext|smartcite|cites)\*?"
    r"(?:\[[^\]]*\])*\{([^}]+)\}",
    re.IGNORECASE,
)
_NOCITE_RE = re.compile(r"\\nocite\*?\{([^}]+)\}", re.IGNORECASE)
_FOOTCITE_RE = re.compile(r"\\footcite\b", re.IGNORECASE)
_FOOTNOTE_RE = re.compile(
    r"\\footnote(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}",
    re.IGNORECASE | re.DOTALL,
)
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MANUAL_BRACKET_CITE_RE = re.compile(
    r"\[(?:\d+(?:-\d+)?)(?:,\s*\d+(?:-\d+)?)*\]",
)
_CITE_BLOCK_RE = re.compile(
    r"\\(?:cite|parencite|textcite|autocite|supercite|footcite|footcitet|"
    r"footcitep|footcitetext|smartcite|cites|nocite)\*?"
    r"(?:\[[^\]]*\])*\{[^}]+\}",
    re.IGNORECASE,
)


def _split_keys(raw: str) -> tuple[str, ...]:
    return tuple(key.strip() for key in raw.split(",") if key.strip())


def cite_keys(text: str) -> frozenset[str]:
    """Collect citation keys from standard cite macros."""
    keys: set[str] = set()
    for match in _CITE_COMMAND_RE.finditer(prepare_body(text)):
        keys.update(_split_keys(match.group(1)))
    return frozenset(keys)


def nocite_keys(text: str) -> frozenset[str]:
    """Collect keys from \\nocite commands."""
    keys: set[str] = set()
    prepared = prepare_body(text)
    for match in _NOCITE_RE.finditer(prepared):
        payload = match.group(1).strip()
        if payload == "*":
            keys.add("*")
            continue
        keys.update(_split_keys(payload))
    return frozenset(keys)


def contains_footcite(text: str) -> bool:
    return _FOOTCITE_RE.search(prepare_body(text)) is not None


def footnote_bibliography_warnings(text: str) -> tuple[str, ...]:
    """Return warning messages for footnotes that look like inline references."""
    warnings: list[str] = []
    for match in _FOOTNOTE_RE.finditer(prepare_body(text)):
        body = match.group(1)
        if _URL_RE.search(body) or _YEAR_RE.search(body):
            warnings.append("сноска с URL или годом издания")
    return tuple(warnings)


def manual_bracket_citations(text: str) -> tuple[str, ...]:
    """Find manual numeric bracket references outside cite macros."""
    prepared = prepare_body(text)
    stripped = _CITE_BLOCK_RE.sub(" ", prepared)
    return tuple(match.group(0) for match in _MANUAL_BRACKET_CITE_RE.finditer(stripped))


def paragraph_chunks(text: str) -> tuple[str, ...]:
    """Split text into non-empty paragraph blocks."""
    chunks = re.split(r"\n\s*\n+", prepare_body(text))
    return tuple(chunk.strip() for chunk in chunks if chunk.strip())


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def paragraphs_without_cite(text: str, *, min_words: int = 150) -> tuple[str, ...]:
    """Return long paragraphs that do not contain a cite macro."""
    long_blocks: list[str] = []
    for chunk in paragraph_chunks(text):
        if word_count(chunk) < min_words:
            continue
        if _CITE_COMMAND_RE.search(chunk) is None:
            long_blocks.append(chunk[:80])
    return tuple(long_blocks)
