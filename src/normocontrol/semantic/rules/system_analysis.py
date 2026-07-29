"""Text-only rule specifications for structural system analysis."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

SSA_01 = RuleSpec(
    rule_id="SSA-01",
    section_roles=("system_analysis",),
    requirement=(
        "Проверь текстовые свидетельства модели текущего состояния as is: описание модели, "
        "явное название допустимой нотации и ссылку на графическую схему. Наличие самого "
        "рисунка проверяет script/vision-слой; не объявляй рисунок существующим только по "
        "текстовому описанию."
    ),
    elements=("as_is_model_description", "notation", "diagram_reference"),
    max_chunks_per_section=3,
    max_total_chunks=3,
)

SSA_02 = RuleSpec(
    rule_id="SSA-02",
    section_roles=("task", "system_analysis"),
    requirement=(
        "Определи применимость по постановке задачи и системному анализу вместе. Прямое "
        "описание программного прототипа, окружения, системы или интеграции означает "
        "программную тематику. Верни not_applicable только при явном свидетельстве "
        "непрограммной тематики. Для программной тематики проверь описание окружения и "
        "текстовые свидетельства таблицы интеграций с системой, адресом и протоколом или API."
    ),
    elements=(
        "software_applicability",
        "environment",
        "integration_system",
        "integration_address",
        "integration_protocol_api",
    ),
    max_chunks_per_section=2,
    max_total_chunks=4,
    require_all_section_roles=True,
)

SSA_03 = RuleSpec(
    rule_id="SSA-03",
    section_roles=("task", "system_analysis"),
    requirement=(
        "Сначала определи по постановке задачи, относится ли работа к вычислительной тематике. "
        "Если нет, верни not_applicable. Для вычислительной тематики проверь текстовые "
        "свидетельства таблицы структуры исходных данных: атрибут, вид, формат, частота, "
        "единица измерения и пример."
    ),
    elements=(
        "computational_applicability",
        "data_attribute",
        "data_kind",
        "data_format",
        "data_frequency",
        "measurement_unit",
        "data_example",
    ),
    max_chunks_per_section=2,
    max_total_chunks=4,
    require_all_section_roles=True,
)

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
