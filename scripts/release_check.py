#!/usr/bin/env python3
"""PoC release gate: lint, types, tests, schema, demo dry-run → build/release-check.json."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE_NAMES = (
    "ruff_format",
    "ruff_check",
    "mypy",
    "pytest",
    "schema",
    "demo_dry_run",
)

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class StageResult:
    """One release-check stage outcome."""

    name: str
    ok: bool
    duration_ms: float
    detail: str = ""


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        list(cmd),
        check=False,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        env=env,
    )


def _python() -> str:
    return sys.executable


def stage_commands() -> dict[str, list[str]]:
    py = _python()
    return {
        "ruff_format": [py, "-m", "ruff", "format", "--check", "."],
        "ruff_check": [py, "-m", "ruff", "check", "."],
        "mypy": [py, "-m", "mypy", "src"],
        "pytest": [py, "-m", "pytest", "-q", "-m", "not live"],
        "schema": [
            py,
            "-c",
            (
                "from pathlib import Path; "
                "from normocontrol.reporting.json_report import load_report_schema; "
                "load_report_schema(); "
                "assert Path('schemas/report.schema.json').is_file()"
            ),
        ],
        "demo_dry_run": [py, str(ROOT / "demo" / "run_demo.py"), "--mode", "dry-run"],
    }


def run_stage(
    name: str,
    *,
    runner: CommandRunner,
    fail_stage: str | None,
    mock: bool,
) -> StageResult:
    started = time.perf_counter()
    if fail_stage == name:
        return StageResult(
            name=name,
            ok=False,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            detail=f"artificial failure requested via --fail-stage={name}",
        )
    if mock:
        return StageResult(
            name=name,
            ok=True,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            detail="mocked success",
        )
    cmd = stage_commands()[name]
    completed = runner(cmd)
    detail = (completed.stderr or completed.stdout or "").strip()
    if len(detail) > 2000:
        detail = detail[:2000] + "...[truncated]"
    return StageResult(
        name=name,
        ok=completed.returncode == 0,
        duration_ms=(time.perf_counter() - started) * 1000.0,
        detail=detail or f"exit={completed.returncode}",
    )


def run_release_check(
    *,
    stages: Sequence[str] = STAGE_NAMES,
    fail_stage: str | None = None,
    mock: bool = False,
    runner: CommandRunner = default_runner,
) -> list[StageResult]:
    unknown = [name for name in stages if name not in STAGE_NAMES]
    if unknown:
        raise ValueError(f"unknown stages: {unknown}; expected {list(STAGE_NAMES)}")
    if fail_stage is not None and fail_stage not in STAGE_NAMES:
        raise ValueError(f"unknown --fail-stage: {fail_stage}")
    results: list[StageResult] = []
    for name in stages:
        result = run_stage(name, runner=runner, fail_stage=fail_stage, mock=mock)
        results.append(result)
        if not result.ok:
            break
    return results


def write_report(
    path: Path,
    results: Sequence[StageResult],
    *,
    expected_stages: Sequence[str],
) -> dict:
    payload = {
        "ok": bool(results)
        and len(results) == len(expected_stages)
        and all(item.ok for item in results),
        "version": "0.1.0",
        "stages": [asdict(item) for item in results],
        "tag_hint": (
            "Create annotated tag v0.1.0 only after merge to main, green required "
            "checks, and signed acceptance checklist. Do not push the tag from "
            "this script."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(ROOT / "build" / "release-check.json"),
        help="JSON report path",
    )
    parser.add_argument(
        "--fail-stage",
        default=None,
        choices=STAGE_NAMES,
        help="Artificially fail this stage (for tests)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Skip real subprocesses; all stages succeed unless --fail-stage",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=STAGE_NAMES,
        help="Run a subset of stages",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stages = tuple(args.only) if args.only else STAGE_NAMES
    try:
        results = run_release_check(
            stages=stages,
            fail_stage=args.fail_stage,
            mock=bool(args.mock),
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    payload = write_report(out, results, expected_stages=stages)
    print(json.dumps({"ok": payload["ok"], "out": str(out)}, ensure_ascii=False))
    for item in results:
        mark = "OK" if item.ok else "FAIL"
        print(f"[{mark}] {item.name} ({item.duration_ms:.0f} ms)")
        if not item.ok and item.detail:
            print(item.detail)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
