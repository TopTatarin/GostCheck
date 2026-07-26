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
