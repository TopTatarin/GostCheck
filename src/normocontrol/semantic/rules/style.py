"""Cross-document causal-chain rule specification."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

GEN_01 = RuleSpec(
    rule_id="GEN-01",
    section_roles=("content",),
    requirement=(
        "По ограниченным выжимкам проверь причинно-следственную цепочку: результат каждого "
        "раздела используется как вход следующего. Не делай вывод о фрагментах вне выжимек. "
        "Явные переходы между всеми доступными этапами означают pass, частичные переходы — warn."
    ),
    elements=("section_handoffs", "causal_chain"),
    max_chunks_per_section=1,
    max_total_chunks=12,
)

GEN_02 = RuleSpec(
    rule_id="GEN-02",
    section_roles=("content",),
    requirement=(
        "Оцени по доступным разделам, понятен ли текст стороннему читателю и достаточно ли "
        "описаны исходные условия, методы, параметры и интерпретация результатов для "
        "воспроизведения. Не оценивай невидимые фрагменты. Полный проверяемый контекст означает "
        "pass; нераскрытые термины или недостающие параметры означают warn."
    ),
    elements=(
        "audience_context",
        "reproducible_method",
        "input_parameters",
        "result_interpretation",
    ),
    max_chunks_per_section=1,
    max_total_chunks=12,
)
