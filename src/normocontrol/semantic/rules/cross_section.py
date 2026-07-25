"""Cross-section rule specifications for goals, tasks and conclusions."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

TSK_01 = RuleSpec(
    rule_id="TSK-01",
    section_roles=("task",),
    requirement=(
        "Проверь наличие резюме анализа с обоснованием, цели, перечня задач и предполагаемого "
        "ключевого результата. Учитывай перефразирование и любой порядок задач. Полный набор "
        "означает pass; частичный или не измеримый набор означает warn."
    ),
    elements=("analysis_summary", "goal", "tasks", "expected_result"),
)

TSK_03 = RuleSpec(
    rule_id="TSK-03",
    section_roles=("task", "results"),
    requirement=(
        "Сопоставь цель и качественные требования из постановки задачи с численными "
        "показателями в анализе результатов. Не засчитывай цель, найденную только в заключении. "
        "Подтверждённое численное соответствие означает pass, только качественное или частичное "
        "соответствие означает warn."
    ),
    elements=("measurable_goal", "quantitative_results", "goal_result_alignment"),
)

CON_01 = RuleSpec(
    rule_id="CON-01",
    section_roles=("task", "conclusion"),
    requirement=(
        "Сопоставь задачи постановки с заключением: полный перечень результатов по задачам, "
        "ключевой результат и количественная оценка достижения цели. Допускай перефразирование "
        "и изменение порядка, но отмечай частично выполненную задачу как weak. Полное "
        "сопоставление означает pass, неполное или только качественное — warn."
    ),
    elements=("task_results", "key_result", "quantitative_goal_assessment"),
)
