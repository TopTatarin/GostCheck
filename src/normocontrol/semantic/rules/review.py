"""Text-only rule specifications for the literature review."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

REV_05 = RuleSpec(
    rule_id="REV-05",
    section_roles=("review",),
    requirement=(
        "Проверь, что обзор строится как сравнение, обобщение и классификация работ, а не как "
        "последовательный пересказ источников. Полная тематическая структура с сопоставлением "
        "подходов означает pass; отдельные сравнения при преобладании пересказа означают warn."
    ),
    elements=("comparison", "synthesis", "classification", "thematic_structure"),
    max_chunks_per_section=3,
    max_total_chunks=3,
)

REV_06 = RuleSpec(
    rule_id="REV-06",
    section_roles=("review",),
    requirement=(
        "Проверь семь аспектов обзора: предпосылки и современное состояние; вопросы обзора; "
        "методику отбора; анализ библиографических метаданных; сравнительный анализ "
        "целей, методов и результатов; ответы на вопросы; вывод с обоснованием выбора метода. "
        "Все аспекты present означают pass; слабый или отсутствующий аспект означает warn."
    ),
    elements=(
        "background_state",
        "review_questions",
        "selection_method",
        "metadata_analysis",
        "comparative_analysis",
        "answers",
        "method_choice_conclusion",
    ),
    max_chunks_per_section=3,
    max_total_chunks=3,
)
