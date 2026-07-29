from __future__ import annotations

from pathlib import Path

from normocontrol.evaluation.semantic import (
    ExpectedOutcome,
    build_synthetic_bundle,
    evaluate_semantic_corpus,
    load_semantic_corpus,
    mock_provider_factory,
)
from normocontrol.semantic.schemas import IMPLEMENTED_RULE_IDS

CORPUS_PATH = Path("tests/fixtures/semantic/corpus.json")


def test_corpus_has_full_sections_and_three_cases_for_every_rule() -> None:
    corpus = load_semantic_corpus(CORPUS_PATH)

    assert len(corpus.fixtures) == 3
    for fixture in corpus.fixtures:
        titles = {section.title for section in fixture.sections}
        assert {
            "Алгоритм",
            "Аннотация",
            "Архитектура",
            "Введение",
            "Математическая модель",
            "Обзор научно-технической информации",
            "Постановка задачи",
            "Программная реализация",
            "Анализ результатов",
            "Структурный системный анализ",
            "Заключение",
        } <= titles
        bundle = build_synthetic_bundle(fixture)
        assert bundle.source_files[0].path.startswith("synthetic/")
        assert all(chunk.token_count <= 800 for chunk in bundle.chunks)

    for rule_id in IMPLEMENTED_RULE_IDS:
        outcomes = {
            expectation.outcome
            for fixture in corpus.fixtures
            for expectation in fixture.expectations
            if expectation.rule_id == rule_id
        }
        assert outcomes == set(ExpectedOutcome)


def test_mock_evaluation_is_reproducible_and_fully_verified() -> None:
    corpus = load_semantic_corpus(CORPUS_PATH)

    first = evaluate_semantic_corpus(
        corpus,
        provider_factory=mock_provider_factory,
        provider_name="synthetic-mock",
        model_id="synthetic-mock-v1",
    )
    second = evaluate_semantic_corpus(
        corpus,
        provider_factory=mock_provider_factory,
        provider_name="synthetic-mock",
        model_id="synthetic-mock-v1",
    )

    assert first == second
    assert [item.rule_id for item in first.rules] == sorted(IMPLEMENTED_RULE_IDS)
    assert all(item.cases == 3 for item in first.rules)
    assert all(item.actionable_cases == 2 for item in first.rules)
    assert all(item.schema_valid_rate == 1.0 for item in first.rules)
    assert all(item.evidence_valid_rate == 1.0 for item in first.rules)
    assert all(item.useful_advisory_rate == 1.0 for item in first.rules)
    assert len(first.observations) == len(IMPLEMENTED_RULE_IDS) * 3
    assert first.schema_validity == 1.0
    assert first.evidence_validity == 1.0
    assert first.useful_advisory_rate == 1.0
    assert first.implemented_rule_count == len(IMPLEMENTED_RULE_IDS)
    assert first.not_implemented_rule_count == 0
    assert set(first.errors_by_rule_id) == IMPLEMENTED_RULE_IDS
    assert all(errors == () for errors in first.errors_by_rule_id.values())
    assert "Объект исследования" not in first.model_dump_json()
