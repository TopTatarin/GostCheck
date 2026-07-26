"""Deterministic, section-scoped batching for semantic rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from normocontrol.extract.base import (
    DocumentBundle,
    DocumentChunk,
    Section,
    SectionKind,
    make_locator,
    sha256_text,
)
from normocontrol.extract.chunking import estimate_tokens


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Static execution contract for one implemented semantic rule."""

    rule_id: str
    section_roles: tuple[str, ...]
    requirement: str
    elements: tuple[str, ...]
    max_chunks_per_section: int = 2
    max_total_chunks: int = 6
    require_all_section_roles: bool = False
    headings_only: bool = False

    def __post_init__(self) -> None:
        if not self.rule_id or not self.section_roles or not self.requirement or not self.elements:
            raise ValueError("semantic rule specification fields must be non-empty")
        if len(set(self.section_roles)) != len(self.section_roles):
            raise ValueError("semantic section roles must be unique")
        if len(set(self.elements)) != len(self.elements):
            raise ValueError("semantic element names must be unique")
        if self.max_chunks_per_section < 1 or self.max_total_chunks < 1:
            raise ValueError("semantic chunk limits must be positive")


@dataclass(frozen=True, slots=True)
class RuleBatch:
    """A bounded set of chunks authorized as evidence for one request."""

    spec: RuleSpec
    sections: tuple[Section, ...]
    chunks: tuple[DocumentChunk, ...]
    missing_roles: tuple[str, ...] = ()
    audit_section_ids: tuple[str, ...] = ()


_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "annotation": ("аннотац", "реферат", "abstract"),
    "introduction": ("введен", "introduction"),
    "task": (
        "постановка задач",
        "цель и задач",
        "цели и задач",
        "problem statement",
        "objectives",
    ),
    "review": (
        "обзор научно технической",
        "обзор нти",
        "литературный обзор",
        "literature review",
        "related work",
    ),
    "system_analysis": (
        "структурный системный анализ",
        "системный анализ",
        "модель as is",
        "as is model",
    ),
    "math_model": (
        "математическая модель",
        "математическое моделирование",
        "math model",
        "mathematical model",
    ),
    "algorithm": (
        "алгоритм",
        "algorithm",
        "псевдокод",
        "pseudocode",
    ),
    "architecture": (
        "архитектурно техническое решение",
        "архитектурное решение",
        "архитектура",
        "модель to be",
        "to be model",
        "architecture",
    ),
    "implementation": (
        "программная реализация",
        "реализация",
        "implementation",
        "software implementation",
    ),
    "results": (
        "анализ результат",
        "результат",
        "оценка эффективност",
        "апробац",
        "results",
        "evaluation",
    ),
    "conclusion": ("заключен", "вывод", "conclusion"),
}
_EXCLUDED_CONTENT = (
    "библиограф",
    "список использованных источников",
    "список литературы",
    "references",
    "приложен",
    "appendix",
)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).casefold().replace("ё", "е")
    return " ".join(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _matches_role(section: Section, role: str) -> bool:
    title = _normalize(f"{section.section_id} {section.title}")
    if role == "subsection_headings":
        return section.level >= 2 and not any(alias in title for alias in _EXCLUDED_CONTENT)
    if role == "annotation":
        return section.kind is SectionKind.ANNOTATION or any(
            alias in title for alias in _ROLE_ALIASES[role]
        )
    if role == "introduction":
        return section.kind is SectionKind.INTRODUCTION or any(
            alias in title for alias in _ROLE_ALIASES[role]
        )
    if role == "conclusion":
        return section.kind is SectionKind.CONCLUSION or any(
            alias in title for alias in _ROLE_ALIASES[role]
        )
    if role == "content":
        return section.kind not in {
            SectionKind.ANNOTATION,
            SectionKind.APPENDIX,
            SectionKind.DOCUMENT,
        } and not any(alias in title for alias in _EXCLUDED_CONTENT)
    return any(alias in title for alias in _ROLE_ALIASES.get(role, (role,)))


def _bounded_section_chunks(
    chunks: tuple[DocumentChunk, ...],
    limit: int,
) -> tuple[DocumentChunk, ...]:
    """Select head/tail context deterministically without forwarding a whole section."""
    ordered = tuple(sorted(chunks, key=lambda item: (item.char_start, item.chunk_id)))
    if len(ordered) <= limit:
        return ordered
    if limit == 1:
        return ordered[:1]
    head_count = (limit + 1) // 2
    tail_count = limit - head_count
    return ordered[:head_count] + ordered[-tail_count:]


def _heading_chunk(bundle: DocumentBundle, section: Section) -> DocumentChunk | None:
    """Publish one exact heading and no section body to heading-only rules."""
    heading_start = bundle.text.find(section.title, section.char_start, section.char_end)
    if heading_start < 0:
        return None
    heading_end = heading_start + len(section.title)
    return DocumentChunk(
        chunk_id=f"heading:{sha256_text(section.title)[:16]}",
        text=bundle.text[heading_start:heading_end],
        token_count=estimate_tokens(section.title),
        source_hash=bundle.source_hash,
        section_id=section.section_id,
        char_start=heading_start,
        content_start=heading_start,
        char_end=heading_end,
        overlap_chars=0,
        page_start=section.page_start,
        page_end=section.page_start,
        quote_locator=make_locator(bundle.source_hash, heading_start, heading_end),
    )


def _audit_section_id(section: Section, *, headings_only: bool) -> str:
    if headings_only:
        return f"heading-section:{sha256_text(section.title)[:16]}"
    return section.section_id


class BatchPlanner:
    """Select only rule-relevant sections and a hard-bounded subset of their chunks."""

    def plan(self, bundle: DocumentBundle, spec: RuleSpec) -> RuleBatch:
        def has_body(section: Section) -> bool:
            section_text = bundle.text[section.char_start : section.char_end]
            lines = section_text.splitlines()
            if lines and _normalize(lines[0]) == _normalize(section.title):
                section_text = "\n".join(lines[1:])
            return bool(section_text.strip())

        selected_sections = tuple(
            sorted(
                (
                    section
                    for section in bundle.sections
                    if any(_matches_role(section, role) for role in spec.section_roles)
                    and has_body(section)
                ),
                key=lambda item: (item.char_start, item.section_id),
            )
        )
        missing_roles = (
            tuple(
                role
                for role in spec.section_roles
                if not any(
                    _matches_role(section, role) and has_body(section)
                    for section in bundle.sections
                )
            )
            if spec.require_all_section_roles
            else ()
        )
        chunks: list[DocumentChunk] = []
        for section in selected_sections:
            candidates: tuple[DocumentChunk, ...]
            if spec.headings_only:
                heading = _heading_chunk(bundle, section)
                candidates = () if heading is None else (heading,)
            else:
                candidates = tuple(
                    chunk for chunk in bundle.chunks if chunk.section_id == section.section_id
                )
            chunks.extend(_bounded_section_chunks(candidates, spec.max_chunks_per_section))
        bounded = tuple(chunks[: spec.max_total_chunks])
        selected_ids = {chunk.section_id for chunk in bounded}
        sections_with_chunks = tuple(
            section for section in selected_sections if section.section_id in selected_ids
        )
        return RuleBatch(
            spec=spec,
            sections=sections_with_chunks,
            chunks=bounded,
            missing_roles=missing_roles,
            audit_section_ids=tuple(
                _audit_section_id(section, headings_only=spec.headings_only)
                for section in sections_with_chunks
            ),
        )
