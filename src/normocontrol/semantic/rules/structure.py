"""Heading-only rule specification for concise thematic subsection names."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

STR_05 = RuleSpec(
    rule_id="STR-05",
    section_roles=("subsection_headings",),
    requirement=(
        "Оцени только переданные названия подразделов: они должны быть лаконичными и "
        "тематическими, а не пересказывать отдельный источник. Заголовки вида «Анализ статьи "
        "<автор>» или эквивалентные им означают warn. Не делай выводов о тексте разделов: "
        "он намеренно не передан."
    ),
    elements=("conciseness", "thematic_focus", "no_source_by_source_heading"),
    max_chunks_per_section=1,
    max_total_chunks=20,
    headings_only=True,
)
