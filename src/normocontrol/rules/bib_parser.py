"""Minimal BibTeX parsing for formal bibliography rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from normocontrol.rules.base import RuleExecutionError


class BibReadError(RuleExecutionError):
    """Raised when a bibliography cannot be decoded without exposing its path."""


@dataclass(frozen=True, slots=True)
class BibEntry:
    """One BibTeX record."""

    key: str
    entry_type: str
    fields: dict[str, str]


def _split_bib_entries(text: str) -> list[str]:
    entries: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        at = text.find("@", index)
        if at < 0:
            break
        brace = text.find("{", at)
        if brace < 0:
            break
        depth = 0
        end = brace
        while end < length:
            char = text[end]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    entries.append(text[at : end + 1])
                    index = end + 1
                    break
            end += 1
        else:
            break
    return entries


def _parse_field_value(raw: str, start: int) -> tuple[str, int] | None:
    index = start
    length = len(raw)
    while index < length and raw[index].isspace():
        index += 1
    if index >= length:
        return None
    if raw[index] == "{":
        depth = 0
        value_start = index + 1
        index += 1
        while index < length:
            char = raw[index]
            if char == "{":
                depth += 1
            elif char == "}":
                if depth == 0:
                    return raw[value_start:index], index + 1
                depth -= 1
            index += 1
        return None
    if raw[index] == '"':
        value_start = index + 1
        index += 1
        chars: list[str] = []
        while index < length:
            char = raw[index]
            if char == "\\" and index + 1 < length:
                chars.append(raw[index + 1])
                index += 2
                continue
            if char == '"':
                return "".join(chars), index + 1
            chars.append(char)
            index += 1
        return None
    value_start = index
    while index < length and raw[index] not in ",\n":
        index += 1
    return raw[value_start:index].strip(), index


def parse_bib_entry(raw: str) -> BibEntry | None:
    """Parse one @type{key, ...} block."""
    stripped = raw.strip()
    if not stripped.startswith("@"):
        return None
    brace = stripped.find("{")
    if brace < 0:
        return None
    entry_type = stripped[1:brace].strip().casefold()
    body = stripped[brace + 1 : -1]
    comma = body.find(",")
    if comma < 0:
        return None
    key = body[:comma].strip()
    fields: dict[str, str] = {}
    index = comma + 1
    while index < len(body):
        while index < len(body) and body[index].isspace():
            index += 1
        if index >= len(body):
            break
        eq = body.find("=", index)
        if eq < 0:
            break
        name = body[index:eq].strip().casefold()
        parsed = _parse_field_value(body, eq + 1)
        if parsed is None:
            break
        value, index = parsed
        fields[name] = value.strip()
        while index < len(body) and body[index] in " \t\n,":
            index += 1
    if not key:
        return None
    return BibEntry(key=key, entry_type=entry_type, fields=fields)


def parse_bib_text(text: str) -> tuple[BibEntry, ...]:
    """Parse all entries from BibTeX source text."""
    entries: list[BibEntry] = []
    for block in _split_bib_entries(text):
        entry = parse_bib_entry(block)
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def load_bib_entries(paths: tuple[Path, ...]) -> tuple[BibEntry, ...]:
    """Load and merge BibTeX entries from readable files."""
    merged: list[BibEntry] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise BibReadError(f"unable to read bibliography: {path.name}") from error
        merged.extend(parse_bib_text(text))
    return tuple(merged)


def entry_field(entry: BibEntry, *names: str) -> str | None:
    """Return the first populated field value."""
    for name in names:
        value = entry.fields.get(name.casefold())
        if value:
            return value
    return None
