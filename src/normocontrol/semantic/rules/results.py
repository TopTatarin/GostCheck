"""Cross-section rule specification for analysis of results."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

RES_01 = RuleSpec(
    rule_id="RES-01",
    section_roles=("task", "results"),
    requirement=(
        "Сопоставь постановку и анализ результатов по восьми аспектам: оценка решения каждой "
        "задачи; итоговые метрики; интерпретация метрик; соответствие критериям; количественная "
        "оценка цели; уровень решения проблемы объекта; ограничения; итоговый вывод. Наличие "
        "таблиц и графиков проверяет script-слой, не имитируй их текстовым выводом."
    ),
    elements=(
        "task_evaluation",
        "final_metrics",
        "metric_interpretation",
        "criteria_alignment",
        "quantitative_goal_assessment",
        "object_problem_resolution",
        "limitations",
        "result_summary",
    ),
    max_chunks_per_section=3,
    max_total_chunks=6,
    require_all_section_roles=True,
)
