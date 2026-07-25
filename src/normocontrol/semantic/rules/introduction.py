"""Rule specification for the introduction."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

INT_01 = RuleSpec(
    rule_id="INT-01",
    section_roles=("introduction",),
    requirement=(
        "Проверь шесть элементов введения: местоположение объекта; масштабность и важность; "
        "задачи и проблемы объекта; аргументированная актуальность; существующие возможности "
        "решения; необходимость решения. Для каждого верни element/state/evidence. Все элементы "
        "present означают pass; любой weak или absent при достаточном тексте означает warn."
    ),
    elements=(
        "object_location",
        "importance",
        "object_problems",
        "relevance",
        "existing_solutions",
        "solution_need",
    ),
)
