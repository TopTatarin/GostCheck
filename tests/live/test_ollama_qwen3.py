from __future__ import annotations

import os

import httpx
import pytest

import scripts.benchmark_llm as benchmark

pytestmark = pytest.mark.live


def test_qwen3_advisory_schema_smoke() -> None:
    if os.environ.get("RUN_LLM_LIVE") != "1":
        pytest.skip("set RUN_LLM_LIVE=1 to enable the local Ollama smoke")

    with httpx.Client(timeout=180.0) as client:
        try:
            available, _ = benchmark.probe_ollama_model(
                client, benchmark.DEFAULT_OLLAMA_URL, benchmark.DEFAULT_MODEL
            )
        except benchmark.BenchmarkError as error:
            pytest.skip(f"local Ollama is unavailable: {error}")
        if not available:
            pytest.skip(f"model {benchmark.DEFAULT_MODEL} is not installed")

        fixture = benchmark._fixture_payload(benchmark.SYNTHETIC_FIXTURE, "ollama")
        messages, _ = benchmark.make_messages(fixture)
        result = benchmark.request_schema(
            client,
            provider="ollama",
            base_url=benchmark.DEFAULT_OLLAMA_URL,
            model=benchmark.DEFAULT_MODEL,
            messages=messages,
            num_ctx=benchmark.DEFAULT_NUM_CTX,
            max_output_tokens=benchmark.DEFAULT_MAX_OUTPUT_TOKENS,
        )

    assert result.response.status in benchmark.ADVISORY_STATUSES
    assert benchmark.SmokeResponse.model_validate(result.response.model_dump()) == result.response
