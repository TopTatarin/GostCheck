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
    max_total_chunks=8,
)
