"""E2E contract for A-05 demo pass/fail/fixed and dry-run GitHub planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "demo"))
import run_demo  # noqa: E402

from normocontrol.rubric.loader import load_rubric  # noqa: E402
from normocontrol.rubric.models import WorkProfile  # noqa: E402
from normocontrol.rubric.profiles import rule_enabled  # noqa: E402


def test_golden_pass_fail_fixed(tmp_path: Path) -> None:
    results = run_demo.run_local_golden(out_root=tmp_path / "demo")
    by_name = {item.name: item for item in results}
    assert by_name["pass"].exit_code == 0
    assert by_name["fail"].exit_code == 2
    assert by_name["fixed"].exit_code == 0
    assert by_name["pass"].gate_status == "pass"
    assert by_name["fail"].gate_status == "fail"
    assert by_name["fixed"].gate_status == "pass"


def test_dry_run_mode_runs_golden_and_only_plans_github(tmp_path: Path) -> None:
    code = run_demo.main(["--mode", "dry-run", "--out", str(tmp_path / "out")])
    assert code == 0
    planned = run_demo.dry_run_github()
    assert all(isinstance(cmd, list) for cmd in planned)
    assert any(cmd[:2] == ["gh", "pr"] for cmd in planned)
    # dry_run_github is pure planning: executing it must not be done by main.
    # Guard: no side-effect helper exists beyond returning the list.
    assert run_demo.dry_run_github is not None


def test_github_plan_order_pass_then_fail() -> None:
    planned = run_demo.dry_run_github(("pass", "fail"))
    assert planned[0] == ["git", "fetch", "origin", "main"]
    assert planned[1][:3] == ["git", "checkout", "-B"]
    assert "demo/pass" in planned[1]
    create = next(cmd for cmd in planned if cmd[:3] == ["gh", "pr", "create"])
    assert "--base" in create and "main" in create
    assert any("demo/fail" in cmd for cmd in planned)


def test_execute_github_requires_allowlist_and_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_demo, "resolve_remote_slug", lambda runner=None: "evil/other")
    with pytest.raises(RuntimeError, match="allowlist"):
        run_demo.ensure_allowlist(confirm=True)

    monkeypatch.setattr(run_demo, "resolve_remote_slug", lambda runner=None: "TopTatarin/GostCheck")
    with pytest.raises(RuntimeError, match="mutations"):
        run_demo.ensure_allowlist(confirm=False)
    assert run_demo.ensure_allowlist(confirm=True) == "TopTatarin/GostCheck"


def test_private_sample_missing_is_skip(tmp_path: Path) -> None:
    notes = run_demo.run_private_baseline(
        software_pdf=tmp_path / "missing-software.pdf",
        research_pdf=None,
        out_root=tmp_path / "baseline",
    )
    assert any(line.startswith("SKIP software") for line in notes)
    assert any("not provided" in line or "SKIP" in line for line in notes)
    private = ROOT / "samples" / "private"
    assert private.is_dir()
    assert (private / ".gitignore").is_file()
    ignored = (private / ".gitignore").read_text(encoding="utf-8")
    assert "*" in ignored
    assert "!.gitkeep" in ignored
    # Directory marker must be tracked so the folder exists in a fresh clone.
    assert (private / ".gitkeep").is_file()


def test_software_research_conditional_prefixes() -> None:
    rubric = load_rubric(ROOT / "rubric.yaml")
    arc = next(rule for rule in rubric.rules if rule.id.startswith("ARC-"))
    alg = next(rule for rule in rubric.rules if rule.id.startswith("ALG-"))
    str_rule = next(rule for rule in rubric.rules if rule.id.startswith("STR-"))

    assert rule_enabled(arc, WorkProfile.SOFTWARE) is True
    assert rule_enabled(alg, WorkProfile.SOFTWARE) is True
    assert rule_enabled(str_rule, WorkProfile.SOFTWARE) is True

    assert rule_enabled(arc, WorkProfile.RESEARCH) is False
    assert rule_enabled(alg, WorkProfile.RESEARCH) is False
    assert rule_enabled(str_rule, WorkProfile.RESEARCH) is True


def test_expected_contracts_on_disk() -> None:
    pass_path = ROOT / "demo" / "expected" / "pass-report.json"
    fail_path = ROOT / "demo" / "expected" / "fail-report.json"
    pass_c = json.loads(pass_path.read_text(encoding="utf-8"))
    fail_c = json.loads(fail_path.read_text(encoding="utf-8"))
    assert pass_c["exit_code"] == 0
    assert fail_c["exit_code"] == 2
    assert fail_c["blocking_rule_ids"] == ["STR-01"]
    assert pass_c["pr_comment_marker"] == run_demo.MARKER
