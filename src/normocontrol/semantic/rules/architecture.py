"""Cross-section rule specifications for architecture decisions."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

ARC_01 = RuleSpec(
    rule_id="ARC-01",
    section_roles=("system_analysis", "architecture"),
    requirement=(
        "Сопоставь модель текущего состояния as is с моделью to be: архитектурное решение "
        "должно отвечать выявленным проблемам, описывать изменения и обосновывать каждое "
        "изменение. Не делай вывод о графике, которого нет в текстовых фрагментах."
    ),
    elements=("as_is_basis", "to_be_model", "change_rationale", "model_traceability"),
    max_chunks_per_section=2,
    max_total_chunks=4,
    require_all_section_roles=True,
)

ARC_02 = RuleSpec(
    rule_id="ARC-02",
    section_roles=("task", "architecture"),
    requirement=(
        "Сопоставь требования постановки с архитектурой: проверь стек реализации, "
        "взаимодействие с окружением и объяснение способов удовлетворения требований. "
        "Все связи должны подтверждаться разрешёнными фрагментами обоих разделов."
    ),
    elements=(
        "requirements_traceability",
        "implementation_stack",
        "environment_interaction",
        "satisfaction_methods",
    ),
    max_chunks_per_section=2,
    max_total_chunks=4,
    require_all_section_roles=True,
)
