from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

import scripts.benchmark_llm as benchmark
from normocontrol.evaluation.semantic import (
    evaluate_semantic_corpus,
    load_semantic_corpus,
    shared_provider_factory,
)
from normocontrol.llm.config import load_llm_config
from normocontrol.llm.ollama import OllamaProvider
from normocontrol.semantic.schemas import IMPLEMENTED_RULE_IDS

pytestmark = pytest.mark.live

CORPUS_PATH = Path("tests/fixtures/semantic/corpus.json")
RESULT_PATH = Path("benchmark-results/semantic-corpus-live.json")


def test_each_implemented_rule_on_synthetic_corpus_via_ollama() -> None:
    if os.environ.get("RUN_LLM_LIVE") != "1":
        pytest.skip("set RUN_LLM_LIVE=1 to enable the synthetic semantic corpus")

    model = os.environ.get("LLM_MODEL", benchmark.DEFAULT_MODEL)
    base_url = os.environ.get("LLM_BASE_URL", benchmark.DEFAULT_OLLAMA_URL)
    try:
        with httpx.Client(timeout=90.0, trust_env=False) as client:
            available, _ = benchmark.probe_ollama_model(client, base_url, model)
            if not available:
                pytest.skip(f"model {model} is not installed")
            config = load_llm_config(
                {
                    "LLM_PROVIDER": "ollama",
                    "LLM_MODEL": model,
                    "LLM_BASE_URL": base_url,
                    "LLM_TIMEOUT": "90",
                    "LLM_MAX_CONCURRENCY": "1",
                    "LLM_NUM_CTX": "8192",
                    "LLM_MAX_OUTPUT_TOKENS": "512",
                }
            )
            provider = OllamaProvider(config, http_client=client)
            report = evaluate_semantic_corpus(
                load_semantic_corpus(CORPUS_PATH),
                provider_factory=shared_provider_factory(provider),
                provider_name=provider.name,
                model_id=model,
            )
            RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
            RESULT_PATH.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except benchmark.BenchmarkError as error:
        pytest.skip(f"local Ollama is unavailable: {error}")
    finally:
        benchmark.stop_ollama_model(model)

    assert {item.rule_id for item in report.rules} == IMPLEMENTED_RULE_IDS
    assert all(item.status.value != "fail" for item in report.observations)
    assert all(item.schema_valid_rate > 0 for item in report.rules)
    assert all(item.evidence_valid_rate > 0 for item in report.rules)
    assert all(item.useful_advisory_rate > 0 for item in report.rules)
