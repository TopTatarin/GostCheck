"""Reproducible, privacy-safe benchmark for GostCheck LLM providers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_MODEL = "qwen3:8b-q4_K_M"
# Explicit IPv4 loopback avoids Windows installations where ``localhost`` resolves
# to an IPv6 listener/proxy while the Ollama tray binds only 127.0.0.1.
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_YANDEX_URL = "https://ai.api.cloud.yandex.net/v1"
DEFAULT_NUM_CTX = 8192
DEFAULT_MAX_OUTPUT_TOKENS = 512
MAX_CONCURRENCY = 1
MIN_RECOMMENDED_NVIDIA_DRIVER_MAJOR = 531
MIN_CPU_RAM_MIB = 12 * 1024
ADVISORY_STATUSES = frozenset({"warn", "info", "not_applicable", "unverifiable"})
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "semantic" / "complete" / "bundle.json"


class BenchmarkError(RuntimeError):
    """A sanitized, user-actionable benchmark failure."""


class StrictModel(BaseModel):
    """Immutable JSON contract with unknown fields forbidden."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class GpuInfo(StrictModel):
    available: bool
    name: str | None = None
    vram_mib: int | None = Field(default=None, ge=0)
    driver_version: str | None = None
    driver_supported: bool | None = None


class ProcessorSplit(StrictModel):
    mode: Literal["gpu", "cpu", "mixed", "unknown"]
    cpu_percent: int | None = Field(default=None, ge=0, le=100)
    gpu_percent: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def percentages_match(self) -> Self:
        if (
            self.cpu_percent is not None
            and self.gpu_percent is not None
            and self.cpu_percent + self.gpu_percent != 100
        ):
            raise ValueError("processor percentages must add up to 100")
        return self


class BenchmarkSettings(StrictModel):
    num_ctx: int = Field(ge=512)
    max_concurrency: Literal[1] = 1
    max_output_tokens: int = Field(ge=1)
    warming_pass: bool
    force_cpu: bool


class TokenMetrics(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class TimingMetrics(StrictModel):
    warmup_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_seconds: float = Field(ge=0, allow_inf_nan=False)
    tokens_per_second: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class BenchmarkRecord(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    provider: Literal["ollama", "yandex"]
    model: str = Field(min_length=1)
    model_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ollama_version: str | None = None
    gpu: GpuInfo
    processor: ProcessorSplit
    settings: BenchmarkSettings
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokens: TokenMetrics
    timing: TimingMetrics
    schema_valid: bool
    advisory_status: Literal["warn", "info", "not_applicable", "unverifiable"]


class SmokeResponse(StrictModel):
    """Advisory-only schema used by both benchmark and live smoke."""

    status: Literal["warn", "info", "not_applicable", "unverifiable"]
    summary: str = Field(min_length=1, max_length=300)


class RequestMetrics(StrictModel):
    response: SmokeResponse
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_seconds: float = Field(ge=0, allow_inf_nan=False)


def parse_nvidia_smi(output: str) -> GpuInfo:
    """Parse stable CSV output from the documented nvidia-smi query."""
    line = next((item.strip() for item in output.splitlines() if item.strip()), "")
    if not line:
        return GpuInfo(available=False)
    columns = [item.strip() for item in line.split(",")]
    if len(columns) < 3:
        raise BenchmarkError("nvidia-smi returned an unexpected CSV response")
    try:
        vram_mib = int(float(columns[1]))
    except ValueError as error:
        raise BenchmarkError("nvidia-smi returned an invalid VRAM value") from error
    driver = columns[2]
    return GpuInfo(
        available=True,
        name=columns[0],
        vram_mib=vram_mib,
        driver_version=driver,
        driver_supported=is_driver_supported(driver),
    )


def is_driver_supported(version: str) -> bool:
    """Apply the documented conservative driver recommendation."""
    match = re.match(r"\s*(\d+)", version)
    return match is not None and int(match.group(1)) >= MIN_RECOMMENDED_NVIDIA_DRIVER_MAJOR


def parse_ollama_ps(output: str, model: str) -> ProcessorSplit:
    """Parse Ollama PROCESSOR values for CPU, GPU, and split placement."""
    candidates = [line for line in output.splitlines() if model.casefold() in line.casefold()]
    line = candidates[-1] if candidates else ""
    if not line:
        return ProcessorSplit(mode="unknown")

    mixed = re.search(r"(\d{1,3})%\s*/\s*(\d{1,3})%\s+(CPU/GPU|GPU/CPU)", line, re.IGNORECASE)
    if mixed:
        first, second = int(mixed.group(1)), int(mixed.group(2))
        cpu, gpu = (first, second) if mixed.group(3).upper() == "CPU/GPU" else (second, first)
        mode: Literal["gpu", "cpu", "mixed"] = "mixed"
        if cpu == 100:
            mode = "cpu"
        elif gpu == 100:
            mode = "gpu"
        return ProcessorSplit(mode=mode, cpu_percent=cpu, gpu_percent=gpu)

    gpu_match = re.search(r"(\d{1,3})%\s+GPU\b", line, re.IGNORECASE)
    cpu_match = re.search(r"(\d{1,3})%\s+CPU\b", line, re.IGNORECASE)
    if gpu_match and cpu_match:
        gpu, cpu = int(gpu_match.group(1)), int(cpu_match.group(1))
        return ProcessorSplit(mode="mixed", cpu_percent=cpu, gpu_percent=gpu)
    if gpu_match:
        gpu = int(gpu_match.group(1))
        return ProcessorSplit(
            mode="gpu" if gpu == 100 else "mixed", cpu_percent=100 - gpu, gpu_percent=gpu
        )
    if cpu_match:
        cpu = int(cpu_match.group(1))
        return ProcessorSplit(
            mode="cpu" if cpu == 100 else "mixed", cpu_percent=cpu, gpu_percent=100 - cpu
        )
    return ProcessorSplit(mode="unknown")


def system_ram_mib() -> int | None:
    """Return physical RAM without adding a platform-specific dependency."""
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong),
                ("avail_phys", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("avail_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("avail_virtual", ctypes.c_ulonglong),
                ("avail_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.total_phys // (1024 * 1024))
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        pages = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return page_size * pages // (1024 * 1024)


def ensure_cpu_ram(ram_mib: int | None) -> None:
    if ram_mib is not None and ram_mib < MIN_CPU_RAM_MIB:
        raise BenchmarkError(
            f"CPU mode needs at least {MIN_CPU_RAM_MIB} MiB RAM; detected {ram_mib} MiB"
        )


def force_cpu_instructions() -> str:
    return (
        "Stop the Ollama tray/daemon that already owns port 11434, then start a new daemon "
        "from PowerShell with: Stop-Process -Name ollama -ErrorAction SilentlyContinue; "
        '$env:CUDA_VISIBLE_DEVICES="-1"; ollama serve. In another shell set the same '
        "variable and rerun this command with --force-cpu."
    )


def validate_force_cpu(environ: Mapping[str, str]) -> None:
    if environ.get("CUDA_VISIBLE_DEVICES", "").strip() != "-1":
        raise BenchmarkError(force_cpu_instructions())
    ensure_cpu_ram(system_ram_mib())


def classify_runtime_error(message: str, num_ctx: int) -> str:
    lowered = message.casefold()
    if any(marker in lowered for marker in ("out of memory", "cuda error", "cuda_malloc")):
        return (
            f"Ollama ran out of memory at num_ctx={num_ctx}; stop other GPU workloads or retry "
            "with a smaller context. A 40K context is not guaranteed to fit in 12 GB VRAM."
        )
    if "address already in use" in lowered or ("bind" in lowered and "11434" in lowered):
        return (
            "Ollama port 11434 is already owned, commonly by the tray daemon. "
            + force_cpu_instructions()
        )
    return "LLM request failed; inspect the local daemon log without sharing document text"


def _run_command(args: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def collect_gpu_info() -> GpuInfo:
    output = _run_command(
        (
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        )
    )
    return GpuInfo(available=False) if output is None else parse_nvidia_smi(output)


def ollama_version() -> str | None:
    return _run_command(("ollama", "--version"))


def ollama_processor_split(model: str) -> ProcessorSplit:
    output = _run_command(("ollama", "ps"))
    return ProcessorSplit(mode="unknown") if output is None else parse_ollama_ps(output, model)


def _json_object(response: httpx.Response, context: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        value = response.json()
    except (httpx.HTTPError, ValueError) as error:
        detail = classify_runtime_error(response.text[:300], DEFAULT_NUM_CTX)
        raise BenchmarkError(f"{context}: {detail}") from error
    if not isinstance(value, dict):
        raise BenchmarkError(f"{context}: provider returned a non-object JSON response")
    return value


def probe_ollama_model(client: httpx.Client, base_url: str, model: str) -> tuple[bool, str | None]:
    """Check the configured model and return its full digest when available."""
    try:
        response = client.get(f"{base_url.rstrip('/')}/api/tags")
        payload = _json_object(response, "Ollama model probe failed")
    except httpx.HTTPError as error:
        raise BenchmarkError("Ollama endpoint is unavailable") from error
    models = payload.get("models")
    if not isinstance(models, list):
        raise BenchmarkError("Ollama model probe returned an invalid models list")
    for item in models:
        if not isinstance(item, dict):
            continue
        names = {str(item.get("name", "")), str(item.get("model", ""))}
        if model in names:
            digest = item.get("digest")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                return True, digest
            return True, None
    return False, None


def _fixture_payload(path: Path, provider: str) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkError("fixture must be a readable UTF-8 JSON file") from error
    if not isinstance(raw, dict):
        raise BenchmarkError("fixture root must be a JSON object")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise BenchmarkError("fixture has no synthetic text")
    if provider == "yandex":
        source_files = raw.get("source_files")
        safe_source = (
            isinstance(source_files, list)
            and bool(source_files)
            and all(
                isinstance(item, dict)
                and str(item.get("path", "")).replace("\\", "/").startswith("synthetic/")
                for item in source_files
            )
        )
        if (
            resolved != SYNTHETIC_FIXTURE.resolve()
            or text != "Abstract\nSynthetic annotation evidence."
            or not safe_source
        ):
            raise BenchmarkError(
                "cloud policy permits only the repository synthetic fixture; "
                "real theses are blocked"
            )
    return raw


def make_messages(fixture: Mapping[str, Any]) -> tuple[list[dict[str, str]], str]:
    text = str(fixture["text"])
    system = (
        "Ты выполняешь только консультативную проверку синтетического фрагмента. "
        "Верни JSON по схеме; статус fail запрещён."
    )
    user = "Кратко оцени полноту синтетической аннотации:\n" + text
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    canonical = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return messages, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_content(payload: Mapping[str, Any], provider: str) -> str:
    if provider == "ollama":
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
    else:
        choices = payload.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise BenchmarkError(f"{provider} returned no assistant JSON content")
    return content


def _optional_nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage(payload: Mapping[str, Any], provider: str) -> tuple[int | None, int | None, int | None]:
    if provider == "ollama":
        input_tokens = _optional_nonnegative_int(payload.get("prompt_eval_count"))
        output_tokens = _optional_nonnegative_int(payload.get("eval_count"))
        total = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return input_tokens, output_tokens, total
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None, None
    return (
        _optional_nonnegative_int(usage.get("prompt_tokens")),
        _optional_nonnegative_int(usage.get("completion_tokens")),
        _optional_nonnegative_int(usage.get("total_tokens")),
    )


def request_schema(
    client: httpx.Client,
    *,
    provider: Literal["ollama", "yandex"],
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    num_ctx: int,
    max_output_tokens: int,
    api_key: str = "",
    clock: Callable[[], float] = time.perf_counter,
) -> RequestMetrics:
    schema = SmokeResponse.model_json_schema()
    if provider == "ollama":
        url = f"{base_url.rstrip('/')}/api/chat"
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {
                "temperature": 0,
                "num_ctx": num_ctx,
                "num_predict": max_output_tokens,
            },
        }
        headers: dict[str, str] = {}
    else:
        url = f"{base_url.rstrip('/')}/chat/completions"
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "max_tokens": max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "GostCheckSmoke", "strict": True, "schema": schema},
            },
        }
        headers = {"Authorization": f"Api-Key {api_key}"}
    started = clock()
    try:
        response = client.post(url, json=body, headers=headers)
        payload = _json_object(response, f"{provider} schema request failed")
    except httpx.HTTPError as error:
        raise BenchmarkError(f"{provider} endpoint is unavailable") from error
    elapsed = max(0.0, clock() - started)
    try:
        parsed = SmokeResponse.model_validate_json(_extract_content(payload, provider))
    except ValueError as error:
        raise BenchmarkError(f"{provider} response failed the advisory JSON schema") from error
    input_tokens, output_tokens, total_tokens = _usage(payload, provider)
    return RequestMetrics(
        response=parsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_seconds=elapsed,
    )


def _cloud_configuration(args: argparse.Namespace, environ: Mapping[str, str]) -> tuple[str, str]:
    if not args.allow_cloud:
        raise BenchmarkError("cloud opt-in is not confirmed; pass --allow-cloud for synthetic data")
    key = environ.get("LLM_API_KEY", "").strip()
    if not key:
        raise BenchmarkError("LLM_API_KEY is required for the Yandex benchmark")
    model = args.model or environ.get("LLM_MODEL", "").strip()
    if not model:
        raise BenchmarkError("Yandex model URI is required through --model or LLM_MODEL")
    return key, model


def build_record(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] = os.environ,
    client: httpx.Client | None = None,
) -> BenchmarkRecord:
    provider: Literal["ollama", "yandex"] = args.provider
    fixture = _fixture_payload(Path(args.fixture), provider)
    messages, prompt_sha256 = make_messages(fixture)
    api_key = ""
    model = args.model
    model_digest: str | None = None
    version: str | None = None
    gpu = collect_gpu_info()
    if args.force_cpu:
        validate_force_cpu(environ)

    if provider == "yandex":
        api_key, model = _cloud_configuration(args, environ)
        base_url = args.base_url or DEFAULT_YANDEX_URL
    else:
        model = model or DEFAULT_MODEL
        base_url = args.base_url or DEFAULT_OLLAMA_URL
        version = ollama_version()
        if version is None:
            raise BenchmarkError("ollama --version failed; install Ollama and add it to PATH")

    owned_client = client is None
    active_client = client or httpx.Client(timeout=args.timeout)
    try:
        if provider == "ollama":
            available, model_digest = probe_ollama_model(active_client, base_url, model)
            if not available:
                raise BenchmarkError(
                    f"Ollama model {model!r} is not installed; run ollama pull {model}"
                )
            if args.expected_digest and model_digest != args.expected_digest:
                raise BenchmarkError("installed Ollama model digest differs from --expected-digest")
        warmup: RequestMetrics | None = None
        if not args.smoke_only:
            warmup = request_schema(
                active_client,
                provider=provider,
                base_url=base_url,
                model=model,
                messages=messages,
                num_ctx=args.num_ctx,
                max_output_tokens=args.max_output_tokens,
                api_key=api_key,
            )
        measured = request_schema(
            active_client,
            provider=provider,
            base_url=base_url,
            model=model,
            messages=messages,
            num_ctx=args.num_ctx,
            max_output_tokens=args.max_output_tokens,
            api_key=api_key,
        )
    finally:
        if owned_client:
            active_client.close()

    processor = (
        ollama_processor_split(model) if provider == "ollama" else ProcessorSplit(mode="unknown")
    )
    if args.force_cpu and processor.mode not in {"cpu", "unknown"}:
        raise BenchmarkError("--force-cpu was requested, but ollama ps reports GPU placement")
    tokens_per_second = (
        measured.output_tokens / measured.latency_seconds
        if measured.output_tokens is not None and measured.latency_seconds > 0
        else None
    )
    return BenchmarkRecord(
        provider=provider,
        model=model,
        model_digest=model_digest,
        ollama_version=version,
        gpu=gpu,
        processor=processor,
        settings=BenchmarkSettings(
            num_ctx=args.num_ctx,
            max_output_tokens=args.max_output_tokens,
            warming_pass=not args.smoke_only,
            force_cpu=args.force_cpu,
        ),
        prompt_sha256=prompt_sha256,
        tokens=TokenMetrics(
            input_tokens=measured.input_tokens,
            output_tokens=measured.output_tokens,
            total_tokens=measured.total_tokens,
        ),
        timing=TimingMetrics(
            warmup_seconds=warmup.latency_seconds if warmup is not None else None,
            latency_seconds=measured.latency_seconds,
            tokens_per_second=tokens_per_second,
        ),
        schema_valid=True,
        advisory_status=measured.response.status,
    )


def atomic_write_json(path: Path, record: BenchmarkRecord) -> None:
    """Never leave a partial benchmark JSON after Ctrl+C or a write failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(record.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("ollama", "yandex"), required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/last.json"))
    parser.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--force-cpu", action="store_true")
    parser.add_argument("--allow-cloud", action="store_true")
    parser.add_argument("--expected-digest", default="")
    parser.add_argument("--smoke-only", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.num_ctx < 512 or args.max_output_tokens < 1 or args.timeout <= 0:
        print("benchmark limits and timeout must be positive", file=sys.stderr)
        return 2
    try:
        record = build_record(args)
        atomic_write_json(args.output, record)
    except KeyboardInterrupt:
        print("benchmark interrupted; no partial JSON was published", file=sys.stderr)
        return 130
    except BenchmarkError as error:
        print(f"benchmark error: {error}", file=sys.stderr)
        return 2
    print(record.model_dump_json(indent=2))
    print(f"benchmark JSON: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
