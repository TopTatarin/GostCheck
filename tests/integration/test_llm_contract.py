from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

import normocontrol.orchestrator as orchestrator_module
from normocontrol.domain import ExitCode
from normocontrol.evaluation.semantic import build_synthetic_bundle, load_semantic_corpus
from normocontrol.llm.base import AdvisoryStatus, ChatMessage, LlmResult, StrictModel
from normocontrol.llm.config import LlmConfig, load_llm_config
from normocontrol.llm.disabled import DisabledProvider
from normocontrol.llm.ollama import OllamaProvider
from normocontrol.llm.yandex import YandexProvider
from normocontrol.orchestrator import run_pipeline
from normocontrol.run_context import RunRequest, parse_only
from normocontrol.semantic.batching import BatchPlanner
from normocontrol.semantic.engine import RULE_SPECS, SemanticEngine
from normocontrol.semantic.schemas import (
    ElementState,
    EvidenceQuote,
    SemanticResponse,
    SemanticStatus,
    SupportedElementAssessment,
)


class ContractAnswer(StrictModel):
    status: str
    note: str


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_three_providers_share_one_non_blocking_domain_contract() -> None:
    expected = ContractAnswer(status="info", note="synthetic")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/api/chat":
            assert body["think"] is False
            assert body["format"]["additionalProperties"] is False
            assert body["options"]["num_ctx"] == 8192
            return httpx.Response(
                200,
                json={
                    "model": "contract-model",
                    "done": True,
                    "done_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": expected.model_dump_json(),
                        "thinking": "",
                    },
                },
                request=request,
            )
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "id": "contract",
                "object": "chat.completion",
                "created": 1,
                "model": "contract-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": expected.model_dump_json(),
                            "refusal": None,
                        },
                    }
                ],
            },
            request=request,
        )

    ollama = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama", "LLM_MODEL": "contract-model"}),
        http_client=client(handler),
    )
    yandex = YandexProvider(
        load_llm_config(
            {
                "LLM_PROVIDER": "yandex",
                "LLM_MODEL": "contract-model",
                "LLM_API_KEY": "contract-secret",
                "ALLOW_CLOUD_DATA": "true",
            }
        ),
        http_client=client(handler),
    )
    disabled = DisabledProvider()
    messages = (ChatMessage(role="user", content="synthetic"),)

    results = [
        provider.complete(messages, ContractAnswer) for provider in (ollama, yandex, disabled)
    ]

    for result in results:
        assert LlmResult[ContractAnswer].model_validate(result.model_dump()) == result
    assert results[0].data == expected
    assert results[1].data == expected
    assert results[2].advisory is not None
    assert results[2].advisory.status is AdvisoryStatus.SKIPPED


def test_disabled_provider_runs_formal_gate_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_provider(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("disabled provider must not construct a network client")

    monkeypatch.setattr(orchestrator_module, "OllamaProvider", forbidden_provider)
    monkeypatch.setattr(orchestrator_module, "YandexProvider", forbidden_provider)
    root = Path(__file__).resolve().parents[2]
    report = run_pipeline(
        RunRequest(
            source=root / "tests" / "fixtures" / "pdf" / "fmt_pass.pdf",
            out_dir=tmp_path / "disabled",
            config_path=root / "normocontrol.yaml.example",
            rubric_path=root / "rubric.yaml",
            provider="disabled",
            only=parse_only(("FMT-01",)),
            tool_version="contract-test",
        )
    )

    formal = next(stage for stage in report.stages if stage.name == "formal")
    semantic = next(stage for stage in report.stages if stage.name == "semantic")
    assert report.exit_code is ExitCode.SUCCESS
    assert formal.findings
    assert all(finding.rule_id == "FMT-01" for finding in formal.findings)
    assert all(finding.status.value == "skipped" for finding in semantic.findings)


def test_pipeline_uses_yaml_model_and_endpoint_without_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[LlmConfig] = []

    class CapturingOllama(DisabledProvider):
        def __init__(self, config: LlmConfig) -> None:
            captured.append(config)

    for name in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_BASE_URL",
        "ALLOW_CLOUD_DATA",
        "LLM_ALLOW_CLOUD_DATA",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(orchestrator_module, "OllamaProvider", CapturingOllama)
    root = Path(__file__).resolve().parents[2]
    config_path = tmp_path / "normocontrol.yaml"
    config_text = (root / "normocontrol.yaml.example").read_text(encoding="utf-8")
    config_path.write_text(
        config_text.replace(
            "provider: disabled\n  model: qwen3:8b-q4_K_M\n  base_url: http://127.0.0.1:11434/v1",
            "provider: ollama\n  model: yaml-contract-model\n  base_url: http://127.0.0.9:11434/v1",
        ),
        encoding="utf-8",
    )

    report = run_pipeline(
        RunRequest(
            source=root / "tests" / "fixtures" / "pdf" / "fmt_pass.pdf",
            out_dir=tmp_path / "yaml-provider",
            config_path=config_path,
            rubric_path=root / "rubric.yaml",
            only=parse_only(("FMT-01",)),
            tool_version="contract-test",
        )
    )

    assert report.exit_code is ExitCode.SUCCESS
    assert len(captured) == 1
    provider_config = captured[0]
    assert provider_config.model == "yaml-contract-model"
    assert provider_config.base_url == "http://127.0.0.9:11434/v1"


@pytest.mark.parametrize(
    "rule_id",
    (
        "ALG-01",
        "ALG-03",
        "ANN-01",
        "ARC-01",
        "ARC-02",
        "GEN-02",
        "IMP-01",
        "MTH-02",
        "MTH-03",
        "RES-01",
        "REV-02",
        "REV-04",
        "REV-05",
        "REV-06",
        "SSA-01",
        "SSA-02",
        "SSA-03",
        "SSA-04",
        "STR-05",
        "TSK-02",
    ),
)
def test_ollama_contract_repairs_invalid_json_then_verifies_exact_evidence(
    rule_id: str,
) -> None:
    corpus = load_semantic_corpus(Path("tests/fixtures/semantic/corpus.json"))
    fixture = next(item for item in corpus.fixtures if item.id == "positive")
    expectation = next(item for item in fixture.expectations if item.rule_id == rule_id)
    bundle = build_synthetic_bundle(fixture)
    quote = expectation.evidence_quote
    assert quote is not None
    owner = next(
        chunk
        for chunk in BatchPlanner().plan(bundle, RULE_SPECS[rule_id]).chunks
        if quote in chunk.text
    )
    evidence = (EvidenceQuote(chunk_id=owner.chunk_id, quote=quote),)
    valid = SemanticResponse(
        rule_id=rule_id,
        status=SemanticStatus.PASS,
        confidence=0.95,
        summary="Синтетический ответ подтверждён точной цитатой.",
        evidence=evidence,
        elements=tuple(
            SupportedElementAssessment(
                element=element,
                state=ElementState.PRESENT,
                evidence=evidence,
            )
            for element in RULE_SPECS[rule_id].elements
        ),
    )
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content)
        requests.append(body)
        response_format = body["format"]
        assert isinstance(response_format, dict)
        assert response_format["additionalProperties"] is False
        content = '{"r":' if len(requests) == 1 else valid.model_dump_json(by_alias=True)
        return httpx.Response(
            200,
            json={
                "model": "contract-model",
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": content, "thinking": ""},
            },
            request=request,
        )

    provider = OllamaProvider(
        load_llm_config({"LLM_PROVIDER": "ollama", "LLM_MODEL": "contract-model"}),
        http_client=client(handler),
    )

    report = SemanticEngine(provider, model_id="contract-model").run(bundle, (rule_id,))

    assert report.findings[0].status is SemanticStatus.PASS
    assert report.findings[0].evidence
    if quote == owner.text:
        assert report.findings[0].evidence[0].locator == owner.quote_locator
    else:
        assert report.findings[0].evidence[0].locator != owner.quote_locator
    assert report.batches[0].attempts == 2
    assert len(requests[1]["messages"]) == 3
