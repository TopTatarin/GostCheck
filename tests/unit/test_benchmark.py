from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import httpx
import jsonschema  # type: ignore[import-untyped]
import pytest

import scripts.benchmark_llm as benchmark

GPU_CSV = "NVIDIA GeForce RTX 4070 SUPER, 12282, 576.80"
DIGEST = "a" * 64


@pytest.mark.parametrize(
    ("processor", "mode", "cpu", "gpu"),
    [
        ("100% GPU", "gpu", 0, 100),
        ("100% CPU", "cpu", 100, 0),
        ("37%/63% CPU/GPU", "mixed", 37, 63),
        ("63%/37% GPU/CPU", "mixed", 37, 63),
    ],
)
def test_parse_ollama_ps_processor_placement(processor: str, mode: str, cpu: int, gpu: int) -> None:
    output = f"NAME ID SIZE PROCESSOR UNTIL\nqwen3:8b-q4_K_M abc 6.2 GB {processor} 4 minutes"

    split = benchmark.parse_ollama_ps(output, "qwen3:8b-q4_K_M")

    assert split.mode == mode
    assert split.cpu_percent == cpu
    assert split.gpu_percent == gpu


def test_gpu_can_exist_while_ollama_has_fallen_back_to_cpu() -> None:
    gpu = benchmark.parse_nvidia_smi(GPU_CSV)
    split = benchmark.parse_ollama_ps(
        "qwen3:8b-q4_K_M abc 6.2 GB 100% CPU 4 minutes", "qwen3:8b-q4_K_M"
    )

    assert gpu.available is True
    assert gpu.vram_mib == 12282
    assert split.mode == "cpu"


def test_no_nvidia_gpu_and_unknown_unloaded_model_are_explicit() -> None:
    assert benchmark.parse_nvidia_smi("").available is False
    assert (
        benchmark.parse_ollama_ps("NAME ID SIZE PROCESSOR UNTIL", benchmark.DEFAULT_MODEL).mode
        == "unknown"
    )


def test_outdated_driver_is_detected_without_rejecting_cpu_fallback() -> None:
    old = benchmark.parse_nvidia_smi("NVIDIA GPU, 12288, 528.49")

    assert old.driver_supported is False
    assert benchmark.is_driver_supported("531.14") is True


def test_invalid_nvidia_smi_csv_is_a_typed_error() -> None:
    with pytest.raises(benchmark.BenchmarkError, match="unexpected CSV"):
        benchmark.parse_nvidia_smi("not,csv")


def test_model_probe_returns_digest_and_detects_a_different_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": benchmark.DEFAULT_MODEL, "digest": DIGEST}]},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found, digest = benchmark.probe_ollama_model(
            client, benchmark.DEFAULT_OLLAMA_URL, benchmark.DEFAULT_MODEL
        )
        missing, _ = benchmark.probe_ollama_model(
            client, benchmark.DEFAULT_OLLAMA_URL, "another:model"
        )

    assert found is True
    assert digest == DIGEST
    assert missing is False


def test_schema_request_accepts_missing_usage_and_backward_clock() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["options"]["num_ctx"] == 8192
        assert body["options"]["num_predict"] == 512
        return httpx.Response(
            200,
            json={"message": {"content": '{"status":"info","summary":"Синтетика"}'}},
            request=request,
        )

    ticks = iter((100.0, 99.0))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = benchmark.request_schema(
            client,
            provider="ollama",
            base_url=benchmark.DEFAULT_OLLAMA_URL,
            model=benchmark.DEFAULT_MODEL,
            messages=[{"role": "user", "content": "синтетика"}],
            num_ctx=8192,
            max_output_tokens=512,
            clock=lambda: next(ticks),
        )

    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.total_tokens is None
    assert result.latency_seconds == 0
    assert result.response.status == "info"


def test_oom_and_tray_port_errors_are_actionable_and_do_not_repeat_payload() -> None:
    oom = benchmark.classify_runtime_error("CUDA out of memory: private thesis text", 32768)
    port = benchmark.classify_runtime_error("bind 127.0.0.1:11434 address already in use", 8192)

    assert "smaller context" in oom
    assert "40K" in oom
    assert "private thesis text" not in oom
    assert "tray" in port
    assert "CUDA_VISIBLE_DEVICES" in port


def test_force_cpu_requires_daemon_restart_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(benchmark.BenchmarkError, match="Stop the Ollama tray"):
        benchmark.validate_force_cpu({})

    monkeypatch.setattr(benchmark, "system_ram_mib", lambda: 32768)
    benchmark.validate_force_cpu({"CUDA_VISIBLE_DEVICES": "-1"})


def test_insufficient_ram_is_rejected_for_cpu_mode() -> None:
    with pytest.raises(benchmark.BenchmarkError, match="at least"):
        benchmark.ensure_cpu_ram(8192)


def test_cloud_guard_requires_opt_in_key_and_exact_synthetic_fixture(tmp_path: Path) -> None:
    parser = benchmark.build_parser()
    args = parser.parse_args(
        [
            "--provider",
            "yandex",
            "--model",
            "gpt://folder/model",
            "--fixture",
            str(benchmark.SYNTHETIC_FIXTURE),
        ]
    )
    with pytest.raises(benchmark.BenchmarkError, match="opt-in"):
        benchmark._cloud_configuration(args, {})
    args.allow_cloud = True
    with pytest.raises(benchmark.BenchmarkError, match="LLM_API_KEY"):
        benchmark._cloud_configuration(args, {})

    real = tmp_path / "thesis.json"
    real.write_text(
        json.dumps({"text": "real thesis", "source_files": [{"path": "student/main.tex"}]}),
        encoding="utf-8",
    )
    with pytest.raises(benchmark.BenchmarkError, match="real theses are blocked"):
        benchmark._fixture_payload(real, "yandex")


def _ollama_args(output: Path, *, expected_digest: str = "") -> Namespace:
    return benchmark.build_parser().parse_args(
        [
            "--provider",
            "ollama",
            "--model",
            benchmark.DEFAULT_MODEL,
            "--fixture",
            str(benchmark.SYNTHETIC_FIXTURE),
            "--output",
            str(output),
            *(["--expected-digest", expected_digest] if expected_digest else []),
        ]
    )


def _ollama_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/tags":
        return httpx.Response(
            200,
            json={"models": [{"name": benchmark.DEFAULT_MODEL, "digest": DIGEST}]},
            request=request,
        )
    body = json.loads(request.content)
    assert body["stream"] is False
    assert body["format"]["additionalProperties"] is False
    return httpx.Response(
        200,
        json={
            "message": {"content": '{"status":"warn","summary":"Только рекомендация"}'},
            "prompt_eval_count": 40,
            "eval_count": 10,
        },
        request=request,
    )


def test_benchmark_record_is_schema_valid_private_and_reproducibly_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmark, "collect_gpu_info", lambda: benchmark.parse_nvidia_smi(GPU_CSV))
    monkeypatch.setattr(benchmark, "ollama_version", lambda: "ollama version 0.9.6")
    monkeypatch.setattr(
        benchmark,
        "ollama_processor_split",
        lambda _: benchmark.ProcessorSplit(mode="mixed", cpu_percent=20, gpu_percent=80),
    )
    args = _ollama_args(tmp_path / "result.json")
    with httpx.Client(transport=httpx.MockTransport(_ollama_transport)) as client:
        record = benchmark.build_record(args, client=client)

    dumped = record.model_dump(mode="json")
    jsonschema.validate(dumped, benchmark.BenchmarkRecord.model_json_schema())
    serialized = record.model_dump_json()
    assert record.settings.num_ctx == 8192
    assert record.settings.max_concurrency == 1
    assert record.settings.max_output_tokens == 512
    assert record.settings.warming_pass is True
    assert record.model_digest == DIGEST
    assert record.tokens.total_tokens == 50
    assert record.schema_valid is True
    assert record.advisory_status == "warn"
    assert "Synthetic annotation evidence" not in serialized
    assert "LLM_API_KEY" not in serialized
    assert not ({"prompt", "document", "api_key"} & set(_all_keys(dumped)))


def _all_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return list(value) + [key for item in value.values() for key in _all_keys(item)]
    if isinstance(value, list):
        return [key for item in value for key in _all_keys(item)]
    return []


def test_changed_model_digest_stops_before_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmark, "collect_gpu_info", lambda: benchmark.GpuInfo(available=False))
    monkeypatch.setattr(benchmark, "ollama_version", lambda: "ollama version test")
    args = _ollama_args(tmp_path / "result.json", expected_digest="b" * 64)
    with (
        httpx.Client(transport=httpx.MockTransport(_ollama_transport)) as client,
        pytest.raises(benchmark.BenchmarkError, match="digest differs"),
    ):
        benchmark.build_record(args, client=client)


def test_atomic_writer_discards_partial_json_after_ctrl_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "benchmark.json"
    target.write_text('{"stable":true}\n', encoding="utf-8")
    baseline = benchmark.BenchmarkRecord.model_validate_json(
        (benchmark.PROJECT_ROOT / "benchmark" / "baseline.example.json").read_text(encoding="utf-8")
    )

    def interrupted(_: object, handle: Any, **__: object) -> None:
        handle.write('{"schema_version":')
        raise KeyboardInterrupt

    monkeypatch.setattr(json, "dump", interrupted)
    with pytest.raises(KeyboardInterrupt):
        benchmark.atomic_write_json(target, baseline)

    assert target.read_text(encoding="utf-8") == '{"stable":true}\n'
    assert list(tmp_path.glob("*.tmp")) == []


def test_baseline_example_matches_public_benchmark_schema() -> None:
    payload = json.loads(
        (benchmark.PROJECT_ROOT / "benchmark" / "baseline.example.json").read_text(encoding="utf-8")
    )

    restored = benchmark.BenchmarkRecord.model_validate(payload)
    jsonschema.validate(payload, benchmark.BenchmarkRecord.model_json_schema())

    assert restored.gpu.name == "NVIDIA GeForce RTX 4070 SUPER"
    assert restored.gpu.vram_mib == 12282
    assert restored.advisory_status in benchmark.ADVISORY_STATUSES
