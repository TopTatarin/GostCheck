"""Text-only rule specification for mathematical-model exposition."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

MTH_02 = RuleSpec(
    rule_id="MTH-02",
    section_roles=("math_model",),
    requirement=(
        "Проверь, что исходные данные введены как символьные переменные, модель дана в общем "
        "виде без численной подстановки, а переменные и формулы пояснены. Все пять аспектов "
        "present означают pass; неполные пояснения или численный пример вместо общей модели "
        "означают warn."
    ),
    elements=(
        "symbolic_inputs",
        "general_form",
        "variable_explanations",
        "formula_explanations",
        "no_numeric_substitution",
    ),
)

MTH_03 = RuleSpec(
    rule_id="MTH-03",
    section_roles=("task", "math_model", "results"),
    requirement=(
        "Сопоставь цель и критерии постановки с методиками расчёта метрик в математической "
        "модели и с показателями анализа результатов. Определения метрик, формулы расчёта, "
        "целевые показатели и их сквозная трассировка должны быть подтверждены цитатами из "
        "соответствующих разделов."
    ),
    elements=(
        "metric_definitions",
        "calculation_methods",
        "goal_indicators",
        "cross_section_traceability",
    ),
    max_chunks_per_section=2,
    max_total_chunks=6,
    require_all_section_roles=True,
)
