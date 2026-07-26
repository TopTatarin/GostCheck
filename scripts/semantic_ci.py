#!/usr/bin/env python3
"""Advisory semantic CI runner: ollama | yandex | disabled (never blocks merge)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

KNOWN_BACKENDS = frozenset({"ollama", "yandex", "disabled"})
DEFAULT_SOURCE = Path("tests/fixtures/demo/pass")
DEFAULT_OUT = Path("build/semantic")


@dataclass(frozen=True, slots=True)
class AdvisoryResult:
    """Normalized advisory outcome written into the CI artifact."""

    provider: str
    status: str
    reason: str
    process_exit: int
    blocks_merge: bool = False
    advisory: bool = True


class UnknownBackendError(ValueError):
    """Raised when LLM_BACKEND / --provider is not a known value."""


def normalize_backend(raw: str | None) -> str:
    """Return a known backend name or raise ``UnknownBackendError``."""
    if raw is None or not str(raw).strip():
        raise UnknownBackendError("backend is empty")
    value = str(raw).strip().casefold()
    if value not in KNOWN_BACKENDS:
        raise UnknownBackendError(
            f"Unknown backend {raw!r}; expected one of: {', '.join(sorted(KNOWN_BACKENDS))}"
        )
    return value


def resolve_backend(
    *,
    cli_provider: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve backend from CLI, then ``LLM_BACKEND``, defaulting to ``disabled``."""
    env = os.environ if environ is None else environ
    if cli_provider is not None and str(cli_provider).strip():
        return normalize_backend(cli_provider)
    raw = env.get("LLM_BACKEND") or env.get("LLM_PROVIDER") or "disabled"
    if not str(raw).strip():
        return "disabled"
    return normalize_backend(raw)


def status_for_process_exit(exit_code: int) -> str:
    """Map a ``normocontrol`` exit code to an explicit advisory status label."""
    mapping = {
        0: "ok",
        2: "formal_findings_ignored",
        3: "config_error_advisory",
        4: "tool_error_advisory",
    }
    return mapping.get(exit_code, f"advisory_exit_{exit_code}")


def normalize_advisory_exit(exit_code: int, *, provider: str) -> AdvisoryResult:
    """Warnings and tool errors become a successful advisory result."""
    status = status_for_process_exit(exit_code)
    if exit_code == 0:
        reason = "semantic advisory completed"
    elif exit_code == 2:
        reason = "formal findings present; semantic job stays advisory and green"
    elif exit_code == 3:
        reason = "configuration/input error normalized to advisory"
    elif exit_code == 4:
        reason = "tool/internal error normalized to advisory"
    else:
        reason = f"process exit {exit_code} normalized to advisory"
    return AdvisoryResult(
        provider=provider,
        status=status,
        reason=reason,
        process_exit=exit_code,
    )


def write_advisory_artifact(out_dir: Path, result: AdvisoryResult) -> Path:
    """Write ``status.json`` advisory artifact (no document text, no secrets)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "advisory": result.advisory,
        "blocks_merge": result.blocks_merge,
        "provider": result.provider,
        "status": result.status,
        "reason": result.reason,
        "process_exit": result.process_exit,
    }
    path = out_dir / "status.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_disabled_artifact(out_dir: Path, *, reason: str = "LLM_BACKEND=disabled") -> Path:
    """Publish a valid skipped artifact without any network calls."""
    return write_advisory_artifact(
        out_dir,
        AdvisoryResult(
            provider="disabled",
            status="skipped",
            reason=reason,
            process_exit=0,
        ),
    )


def _run_normocontrol(
    *,
    provider: str,
    source: Path,
    out_dir: Path,
    allow_cloud_data: bool,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = dict(os.environ if environ is None else environ)
    env["LLM_PROVIDER"] = provider
    env["LLM_BACKEND"] = provider
    if provider == "yandex":
        # Prefer dedicated Actions secret name when present.
        if not env.get("LLM_API_KEY") and env.get("YANDEX_AI_API_KEY"):
            env["LLM_API_KEY"] = env["YANDEX_AI_API_KEY"]
        env["ALLOW_CLOUD_DATA"] = "true" if allow_cloud_data else "false"
    cmd = [
        sys.executable,
        "-m",
        "normocontrol.cli",
        "run",
        str(source),
        "--provider",
        provider,
        "--out",
        str(out_dir),
        "--config",
        "normocontrol.yaml.example",
        "--rubric",
        "rubric.yaml",
    ]
    completed = subprocess.run(cmd, check=False, env=env)
    return int(completed.returncode)


def run_semantic_ci(
    *,
    provider: str | None,
    source: Path = DEFAULT_SOURCE,
    out_dir: Path = DEFAULT_OUT,
    allow_cloud_data: bool = False,
    environ: Mapping[str, str] | None = None,
) -> AdvisoryResult:
    """Execute advisory semantic CI for one backend and always return a result."""
    backend = resolve_backend(cli_provider=provider, environ=environ)
    env = os.environ if environ is None else environ
    if backend == "disabled":
        write_disabled_artifact(out_dir)
        return AdvisoryResult(
            provider="disabled",
            status="skipped",
            reason="LLM_BACKEND=disabled",
            process_exit=0,
        )

    if backend == "yandex" and not allow_cloud_data:
        result = AdvisoryResult(
            provider="yandex",
            status="cloud_blocked",
            reason="ALLOW_CLOUD_DATA is not true; cloud advisory skipped",
            process_exit=0,
        )
        write_advisory_artifact(out_dir, result)
        return result

    if backend == "yandex" and not (
        env.get("LLM_API_KEY", "").strip() or env.get("YANDEX_AI_API_KEY", "").strip()
    ):
        result = AdvisoryResult(
            provider="yandex",
            status="cloud_credentials_missing",
            reason="Yandex API key is not configured; cloud advisory skipped",
            process_exit=0,
        )
        write_advisory_artifact(out_dir, result)
        return result

    code = _run_normocontrol(
        provider=backend,
        source=source,
        out_dir=out_dir,
        allow_cloud_data=allow_cloud_data,
        environ=environ,
    )
    result = normalize_advisory_exit(code, provider=backend)
    write_advisory_artifact(out_dir, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        "-Provider",
        dest="provider",
        default=None,
        help="ollama | yandex | disabled (default: LLM_BACKEND / disabled)",
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="Demo or thesis path for advisory run",
    )
    parser.add_argument(
        "--out",
        "-Out",
        dest="out",
        default=str(DEFAULT_OUT),
        help="Artifact output directory",
    )
    parser.add_argument(
        "--allow-cloud-data",
        action="store_true",
        help="Permit sending document text to Yandex (opt-in)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_semantic_ci(
            provider=args.provider,
            source=Path(args.source),
            out_dir=Path(args.out),
            allow_cloud_data=bool(args.allow_cloud_data),
        )
    except UnknownBackendError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "advisory": result.advisory,
                "blocks_merge": result.blocks_merge,
                "provider": result.provider,
                "status": result.status,
                "reason": result.reason,
                "process_exit": result.process_exit,
            },
            ensure_ascii=False,
        )
    )
    # Advisory jobs must stay green even when the underlying process failed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
