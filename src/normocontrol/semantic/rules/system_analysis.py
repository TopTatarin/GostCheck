"""Text-only rule specifications for structural system analysis."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

SSA_04 = RuleSpec(
    rule_id="SSA-04",
    section_roles=("system_analysis",),
    requirement=(
        "Проверь предпроектную границу раздела: текст должен описывать текущее состояние "
        "объекта (as is), его проблемы и ограничения, не подменяя анализ описанием готового "
        "решения ВКР. Явная граница текущего состояния означает pass; смешение as is и "
        "предлагаемого решения означает warn."
    ),
    elements=("as_is_description", "current_problems", "preproject_boundary"),
)
