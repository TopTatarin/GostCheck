"""Text-only rule specification for algorithm representation."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

ALG_01 = RuleSpec(
    rule_id="ALG-01",
    section_roles=("algorithm",),
    requirement=(
        "Оцени только текстово доступную часть правила: назван ли тип представления алгоритма "
        "(блок-схема или псевдокод), соответствует ли он тематике и описана ли "
        "последовательность шагов. Наличие графического файла проверяет отдельный script-слой; "
        "не делай вывод о невидимом изображении."
    ),
    elements=("representation_type", "topic_fit", "step_sequence"),
)

ALG_03 = RuleSpec(
    rule_id="ALG-03",
    section_roles=("algorithm",),
    requirement=(
        "Сопоставь нумерованные блоки или строки алгоритма с потекстовым описанием по пунктам. "
        "Каждый блок должен иметь номер, отдельное объяснение и однозначное соответствие "
        "представлению алгоритма. Полное покрытие означает pass; пропуски или ненумерованное "
        "описание означают warn."
    ),
    elements=("numbered_blocks", "textual_descriptions", "one_to_one_coverage"),
)
