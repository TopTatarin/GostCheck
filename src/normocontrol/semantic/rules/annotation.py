"""Rule specification for the thesis annotation."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

ANN_01 = RuleSpec(
    rule_id="ANN-01",
    section_roles=("annotation",),
    requirement=(
        "Проверь шесть элементов аннотации: объект и проблема; актуальность и значимость; "
        "цель; 3–4 задачи; результаты; структура ВКР. Для каждого верни element/state/evidence. "
        "Все элементы present означают pass; любой weak или absent при достаточном тексте "
        "означает warn."
    ),
    elements=("object_problem", "relevance", "goal", "tasks", "results", "structure"),
)
