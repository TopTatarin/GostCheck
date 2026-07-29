"""Text-only rule specifications for the literature review."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

REV_02 = RuleSpec(
    rule_id="REV-02",
    section_roles=("review",),
    requirement=(
        "Проверь только пограничные случаи формальной эвристики по доступному тексту обзора: "
        "есть ли проверяемые признаки зарубежного издания, рецензируемого типа публикации и "
        "основание для вывода о количестве таких источников. Не считай латиницу сама по себе "
        "доказательством рецензирования. Если метаданных недостаточно, верни unverifiable."
    ),
    elements=(
        "foreign_publication_metadata",
        "peer_review_evidence",
        "minimum_count_basis",
    ),
    max_chunks_per_section=3,
    max_total_chunks=3,
)

REV_04 = RuleSpec(
    rule_id="REV-04",
    section_roles=("review",),
    requirement=(
        "Классифицируй пограничные источники только по явно приведённым метаданным и отметь "
        "признаки запрещённых типов: учебник, методическое пособие, ВКР, препринт без сведений "
        "о публикации, научно-популярный сайт или энциклопедия. Не делай вывод по одному "
        "названию; при недостатке метаданных верни unverifiable."
    ),
    elements=(
        "source_type_metadata",
        "prohibited_type_assessment",
        "publication_status",
    ),
    max_chunks_per_section=3,
    max_total_chunks=3,
)

REV_05 = RuleSpec(
    rule_id="REV-05",
    section_roles=("review",),
    requirement=(
        "Проверь, что обзор строится как сравнение, обобщение и классификация работ, а не как "
        "последовательный пересказ источников. Полная тематическая структура с сопоставлением "
        "подходов означает pass; отдельные сравнения при преобладании пересказа означают warn."
    ),
    elements=("comparison", "synthesis", "classification", "thematic_structure"),
    max_chunks_per_section=3,
    max_total_chunks=3,
)

REV_06 = RuleSpec(
    rule_id="REV-06",
    section_roles=("review",),
    requirement=(
        "Проверь семь аспектов обзора: предпосылки и современное состояние; вопросы обзора; "
        "методику отбора; анализ библиографических метаданных; сравнительный анализ "
        "целей, методов и результатов; ответы на вопросы; вывод с обоснованием выбора метода. "
        "Все аспекты present означают pass; слабый или отсутствующий аспект означает warn."
    ),
    elements=(
        "background_state",
        "review_questions",
        "selection_method",
        "metadata_analysis",
        "comparative_analysis",
        "answers",
        "method_choice_conclusion",
    ),
    max_chunks_per_section=3,
    max_total_chunks=3,
)
