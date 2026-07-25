#!/usr/bin/env python3
"""Reproducible demo: local pass/fail/fixed golden checks and optional GitHub PR dry-run."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_PASS = ROOT / "tests" / "fixtures" / "demo" / "pass"
DEMO_FAIL = ROOT / "tests" / "fixtures" / "demo" / "fail"
EXPECTED_PASS = ROOT / "demo" / "expected" / "pass-report.json"
EXPECTED_FAIL = ROOT / "demo" / "expected" / "fail-report.json"
PRIVATE_DIR = ROOT / "samples" / "private"
DEFAULT_ALLOWLIST = frozenset({"TopTatarin/GostCheck"})
MARKER = "<!-- normocontrol-report -->"

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class DemoResult:
    """Outcome of one local demo run."""

    name: str
    exit_code: int
    gate_status: str
    out_dir: Path


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        check=False,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )


def find_normocontrol() -> list[str]:
    """Resolve the ``normocontrol`` CLI without executing ``cli.py`` as a script.

    Running ``src/normocontrol/cli.py`` directly puts that package dir on
    ``sys.path`` and shadows the stdlib ``logging`` module. Prefer the venv
    console script, then PATH, then ``python -c`` with ``PYTHONPATH=src``.
    """
    candidates = [
        ROOT / ".venv312" / "Scripts" / "normocontrol.exe",
        ROOT / ".venv312" / "bin" / "normocontrol",
        Path(sys.executable).with_name("normocontrol.exe"),
        Path(sys.executable).with_name("normocontrol"),
    ]
    for path in candidates:
        if path.is_file():
            return [str(path)]
    which = shutil.which("normocontrol")
    if which:
        return [which]
    # Fallback: import the installed/src package correctly (not as a script file).
    bootstrap = (
        "import sys; "
        "from normocontrol.cli import app; "
        "sys.argv = ['normocontrol'] + sys.argv[1:]; "
        "raise SystemExit(app())"
    )
    return [sys.executable, "-c", bootstrap]


def _normocontrol_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
    if extra_env:
        env.update(extra_env)
    return env


def run_normocontrol(
    source: Path,
    out_dir: Path,
    *,
    profile: str | None = None,
    provider: str = "disabled",
    runner: CommandRunner | None = None,
    extra_env: dict[str, str] | None = None,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        *find_normocontrol(),
        "run",
        str(source),
        "--provider",
        provider,
        "--out",
        str(out_dir),
        "--config",
        str(ROOT / "normocontrol.yaml.example"),
        "--rubric",
        str(ROOT / "rubric.yaml"),
    ]
    if profile:
        cmd.extend(["--profile", profile])
    env = _normocontrol_env(extra_env)
    if runner is None:
        completed = subprocess.run(
            cmd,
            check=False,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            env=env,
        )
        if completed.returncode not in {0, 2} and (completed.stderr or completed.stdout):
            sys.stderr.write(completed.stderr or completed.stdout or "")
        return int(completed.returncode)
    completed = runner(cmd)
    return int(completed.returncode)


def load_report(out_dir: Path) -> dict:
    path = out_dir / "report.json"
    return json.loads(path.read_text(encoding="utf-8"))


def contract_from_report(report: dict) -> dict:
    """Stable demo contract fields (no timestamps / commit / durations)."""
    findings = report.get("findings") or []
    blocking_ids = sorted(
        {
            str(item["rule_id"])
            for item in findings
            if item.get("rule_id")
            and item.get("status") == "fail"
            and item.get("severity") == "error"
            and item.get("layer") == "script"
        }
    )
    header = report.get("header") or {}
    counts = report.get("counts") or {}
    return {
        "schema_version": report.get("schema_version"),
        "exit_code": report.get("exit_code"),
        "gate_status": header.get("gate_status"),
        "profile": header.get("profile"),
        "counts": {
            "formal_errors": counts.get("formal_errors"),
            "approvals_required": counts.get("approvals_required"),
        },
        "blocking_rule_ids": blocking_ids,
        "marker": MARKER,
        "required_github_checks": ["lint-and-unit", "formal-gate"],
        "never_required_github_checks": [
            "build-latex",
            "publish-report",
            "semantic-ollama",
            "semantic-yandex",
            "semantic-disabled",
            "publish-semantic",
        ],
        "pr_comment_marker": MARKER,
        "manual_approval": (
            "Нормоконтролёр подтверждает merge после зелёного formal-gate (и advisory comment)."
        ),
    }


def assert_matches_expected(report: dict, expected_path: Path) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = contract_from_report(report)
    for key in (
        "exit_code",
        "gate_status",
        "counts",
        "blocking_rule_ids",
        "schema_version",
    ):
        if actual.get(key) != expected.get(key):
            raise AssertionError(
                f"demo contract mismatch on {key}: actual={actual.get(key)!r} "
                f"expected={expected.get(key)!r} ({expected_path.name})"
            )


def prepare_fixed_fixture(tmp_root: Path) -> Path:
    """Copy fail fixture and restore STR-01 section order from pass (exit 0)."""
    fixed = tmp_root / "fixed"
    if fixed.exists():
        shutil.rmtree(fixed)
    shutil.copytree(DEMO_FAIL, fixed)
    shutil.copy2(DEMO_PASS / "main.tex", fixed / "main.tex")
    return fixed


def run_local_golden(
    *,
    out_root: Path,
    runner: CommandRunner | None = None,
) -> list[DemoResult]:
    """E2E golden: pass→0, fail→2, fixed→0; compare demo/expected contracts."""
    run = runner or default_runner
    results: list[DemoResult] = []

    pass_out = out_root / "pass"
    code = run_normocontrol(DEMO_PASS, pass_out, runner=run)
    report = load_report(pass_out)
    assert_matches_expected(report, EXPECTED_PASS)
    if code != 0:
        raise AssertionError(f"pass demo expected exit 0, got {code}")
    results.append(DemoResult("pass", code, str(report["header"]["gate_status"]), pass_out))

    fail_out = out_root / "fail"
    code = run_normocontrol(DEMO_FAIL, fail_out, runner=run)
    report = load_report(fail_out)
    assert_matches_expected(report, EXPECTED_FAIL)
    if code != 2:
        raise AssertionError(f"fail demo expected exit 2, got {code}")
    results.append(DemoResult("fail", code, str(report["header"]["gate_status"]), fail_out))

    fixed_src = prepare_fixed_fixture(out_root / "_fixtures")
    fixed_out = out_root / "fixed"
    code = run_normocontrol(fixed_src, fixed_out, runner=run)
    report = load_report(fixed_out)
    if code != 0:
        raise AssertionError(f"fixed demo expected exit 0, got {code}")
    if report["header"]["gate_status"] != "pass":
        raise AssertionError("fixed demo gate_status must be pass")
    if int(report["counts"]["formal_errors"]) != 0:
        raise AssertionError("fixed demo must clear formal_errors")
    results.append(DemoResult("fixed", code, str(report["header"]["gate_status"]), fixed_out))
    return results


def github_plan(scenario: str) -> list[list[str]]:
    """Ordered git/gh commands for demo PRs (not executed in dry-run)."""
    if scenario == "pass":
        branch = "demo/pass"
        title = "demo: formal pass fixture"
        body = (
            "Synthetic pass demo. Expect required checks lint-and-unit + formal-gate green. "
            f"PR comment marker: {MARKER}"
        )
        # Safe text tweak under fixtures is documented; execute mode uses a temp commit message.
        return [
            ["git", "fetch", "origin", "main"],
            ["git", "checkout", "-B", branch, "origin/main"],
            ["git", "status", "--short"],
            [
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ],
        ]
    if scenario == "fail":
        branch = "demo/fail"
        title = "demo: formal fail then fix"
        body = (
            "Controlled STR-01 violation. formal-gate must block merge until fix commit. "
            f"Marker: {MARKER}"
        )
        return [
            ["git", "fetch", "origin", "main"],
            ["git", "checkout", "-B", branch, "origin/main"],
            ["git", "status", "--short"],
            [
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ],
        ]
    raise ValueError(f"unknown scenario: {scenario}")


def resolve_remote_slug(runner: CommandRunner = default_runner) -> str:
    completed = runner(["git", "remote", "get-url", "origin"])
    if completed.returncode != 0:
        raise RuntimeError("cannot resolve git remote origin")
    url = (completed.stdout or "").strip()
    if url.endswith(".git"):
        url = url[:-4]
    if "github.com" in url:
        # git@github.com:Owner/Repo or https://github.com/Owner/Repo
        part = url.split("github.com", 1)[1].lstrip("/:")
        return part
    return url


def ensure_allowlist(
    *,
    allowlist: frozenset[str] = DEFAULT_ALLOWLIST,
    runner: CommandRunner = default_runner,
    confirm: bool = False,
) -> str:
    slug = resolve_remote_slug(runner=runner)
    if slug not in allowlist:
        raise RuntimeError(
            f"remote {slug!r} is not in allowlist {sorted(allowlist)}; refusing --execute-github"
        )
    if not confirm:
        raise RuntimeError("refusing GitHub mutations without --i-understand-github-mutations")
    return slug


def dry_run_github(scenarios: Sequence[str] = ("pass", "fail")) -> list[list[str]]:
    planned: list[list[str]] = []
    for scenario in scenarios:
        planned.extend(github_plan(scenario))
    return planned


def run_private_baseline(
    *,
    software_pdf: Path | None,
    research_pdf: Path | None,
    out_root: Path,
    runner: CommandRunner | None = None,
) -> list[str]:
    """Exploratory/legacy baseline for local private PDFs; skip if missing."""
    notes: list[str] = []
    out_root.mkdir(parents=True, exist_ok=True)
    marker_path = out_root / "LEGACY_INPUT.txt"
    marker_path.write_text(
        (
            "exploratory/legacy-input: historical theses are not expected "
            "to match draft 2026 rubric.\n"
        ),
        encoding="utf-8",
    )

    def _one(label: str, path: Path | None, profile: str) -> None:
        if path is None:
            notes.append(f"SKIP {label}: path not provided")
            return
        if not path.is_file():
            notes.append(f"SKIP {label}: file not found: {path}")
            return
        dest = out_root / label
        code = run_normocontrol(path, dest, profile=profile, runner=runner)
        report = load_report(dest)
        report.setdefault("header", {})
        # Annotate on-disk copy for humans (do not mutate schema unexpectedly in git).
        meta = {
            "exploratory": True,
            "legacy_input": True,
            "profile": profile,
            "source_name": path.name,
            "exit_code": code,
            "gate_status": report.get("header", {}).get("gate_status"),
            "note": "Not a claim that historical work must satisfy the draft rubric.",
        }
        (dest / "legacy_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        notes.append(f"OK {label}: exit={code} profile={profile} out={dest}")

    _one("software", software_pdf, "software")
    _one("research", research_pdf, "research")
    if not notes:
        notes.append(f"SKIP all: place PDFs under {PRIVATE_DIR} or pass explicit paths")
    return notes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("dry-run", "local", "execute-github", "baseline"),
        default="dry-run",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "build" / "demo"),
        help="Output root under build/ (gitignored)",
    )
    parser.add_argument(
        "--software-pdf",
        default="",
        help="Local private PDF for software profile baseline",
    )
    parser.add_argument(
        "--research-pdf",
        default="",
        help="Local private PDF for research profile baseline",
    )
    parser.add_argument(
        "--i-understand-github-mutations",
        action="store_true",
        help="Required together with --mode execute-github",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = ROOT / out_root

    if args.mode in {"dry-run", "local"}:
        results = run_local_golden(out_root=out_root)
        for item in results:
            print(f"{item.name}: exit={item.exit_code} gate={item.gate_status} out={item.out_dir}")
        planned = dry_run_github()
        print("GitHub plan (not executed):")
        for cmd in planned:
            print(" ", " ".join(cmd))
        if args.mode == "dry-run":
            print("dry-run: no gh/git mutations")
        return 0

    if args.mode == "baseline":
        software = Path(args.software_pdf) if args.software_pdf else None
        research = Path(args.research_pdf) if args.research_pdf else None
        # Convenience defaults inside samples/private if present
        if software is None:
            candidate = PRIVATE_DIR / "anisimova.pdf"
            software = candidate if candidate.is_file() else None
        if research is None:
            candidate = PRIVATE_DIR / "zoloev.pdf"
            research = candidate if candidate.is_file() else None
        notes = run_private_baseline(
            software_pdf=software,
            research_pdf=research,
            out_root=out_root / "baseline",
        )
        for line in notes:
            print(line)
        return 0

    if args.mode == "execute-github":
        ensure_allowlist(confirm=args.i_understand_github_mutations)
        print(
            "execute-github is intentionally conservative in this PoC script:\n"
            "create branches/commits manually from tests/fixtures/demo/{pass,fail}, then:\n"
        )
        for cmd in dry_run_github():
            print(" ", " ".join(cmd))
        print(
            "\nRefusing automatic git commit/push/merge/delete. "
            "Re-run commands yourself after reviewing the diff."
        )
        return 0

    raise AssertionError(f"unhandled mode {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
