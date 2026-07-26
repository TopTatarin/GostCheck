"""Cross-section rule specification for implementation exposition."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

IMP_01 = RuleSpec(
    rule_id="IMP-01",
    section_roles=("architecture", "implementation", "results"),
    requirement=(
        "Сопоставь архитектуру, программную реализацию и результаты: стек должен быть описан "
        "последовательно, порядок тестирования определён, наборы данных названы, а "
        "промежуточные результаты оценены. Состав оценивай только по выбранной программной "
        "тематике и доступным фрагментам."
    ),
    elements=("stack_sequence", "testing_order", "datasets", "intermediate_results"),
    max_chunks_per_section=2,
    max_total_chunks=6,
    require_all_section_roles=True,
)
