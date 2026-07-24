"""LaTeX float, label, ref and caption extraction for formal rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

from normocontrol.extract.latex import (
    _protect_literal_environments,
    _restore_protected,
    _strip_comments,
)

_FLOAT_BLOCK_RE = re.compile(
    r"\\begin\{(figure|table|longtable)\*?\}(.*?)\\end\{\1\*?\}",
    re.DOTALL | re.IGNORECASE,
)
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_REF_RE = re.compile(
    r"\\(?:ref|pageref|autoref|eqref|cref|Cref|risref)\*?\{([^}]+)\}",
    re.IGNORECASE,
)
_CAPTION_RE = re.compile(
    r"\\caption\*?(?:\[(?:[^{}]|\{[^{}]*\})*\])?\{((?:[^{}]|\{[^{}]*\})*)\}",
    re.DOTALL,
)
_FIGURE_NUMBER_RE = re.compile(r"Рисунок\s+(\d+)", re.IGNORECASE)
_ABBREV_FIGURE_RE = re.compile(r"[Рр]ис\.(?:\s*|~)\s*\d")
_DISPLAY_MATH_RE = re.compile(
    r"\\\[|\\begin\s*\{equation\*+\}|\\begin\s*\{displaymath\}|\$\$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FloatBlock:
    """One figure/table/longtable environment."""

    environment: str
    label: str | None
    caption: str | None
    body: str
    start: int
    end: int


def prepare_body(text: str) -> str:
    """Strip comments and restore protected literal environments."""
    opaque, protected = _protect_literal_environments(text)
    stripped = _strip_comments(opaque)
    return _restore_protected(stripped, protected)


def find_float_blocks(text: str) -> tuple[FloatBlock, ...]:
    """Return all float-like environments in document order."""
    prepared = prepare_body(text)
    blocks: list[FloatBlock] = []
    for match in _FLOAT_BLOCK_RE.finditer(prepared):
        inner = match.group(2)
        label_match = _LABEL_RE.search(inner)
        caption_match = _CAPTION_RE.search(inner)
        blocks.append(
            FloatBlock(
                environment=match.group(1).casefold(),
                label=label_match.group(1).strip() if label_match else None,
                caption=caption_match.group(1).strip() if caption_match else None,
                body=inner,
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(blocks)


def figure_blocks(text: str) -> tuple[FloatBlock, ...]:
    return tuple(block for block in find_float_blocks(text) if block.environment == "figure")


def table_blocks(text: str) -> tuple[FloatBlock, ...]:
    return tuple(
        block
        for block in find_float_blocks(text)
        if block.environment in {"table", "longtable"}
    )


def reference_targets(text: str) -> tuple[str, ...]:
    """Collect all labels referenced outside float bodies."""
    prepared = prepare_body(text)
    blocks = find_float_blocks(prepared)
    excluded_ranges = [(block.start, block.end) for block in blocks]

    def outside_floats(start: int) -> bool:
        return all(
            not (block_start <= start < block_end)
            for block_start, block_end in excluded_ranges
        )

    labels: list[str] = []
    for match in _REF_RE.finditer(prepared):
        if outside_floats(match.start()):
            labels.append(match.group(1).strip())
    return tuple(labels)


def caption_arguments(text: str) -> tuple[str, ...]:
    prepared = prepare_body(text)
    return tuple(match.group(1).strip() for match in _CAPTION_RE.finditer(prepared))


def figure_number_from_caption(caption: str | None) -> int | None:
    if caption is None:
        return None
    match = _FIGURE_NUMBER_RE.search(caption)
    if match is None:
        return None
    return int(match.group(1))


def contains_abbreviated_figure_reference(text: str) -> bool:
    return _ABBREV_FIGURE_RE.search(prepare_body(text)) is not None


def contains_unnumbered_display_math(text: str) -> bool:
    return _DISPLAY_MATH_RE.search(prepare_body(text)) is not None


def longtable_without_continuation_header(text: str) -> bool:
    """Return True when a longtable lacks continuation header markup."""
    prepared = prepare_body(text)
    for match in re.finditer(r"\\begin\{longtable\*?\}", prepared, re.IGNORECASE):
        snippet = prepared[match.start() : match.start() + 800]
        if not re.search(r"\\end(?:first)?head\b", snippet, re.IGNORECASE):
            return True
    return False
