"""Unit tests for advisory semantic CI config and workflow guards."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "semantic-advisory.yml"
FORMAL_WORKFLOW = ROOT / ".github" / "workflows" / "normocontrol.yml"
SCRIPT = ROOT / "scripts" / "semantic_ci.py"

sys.path.insert(0, str(ROOT / "scripts"))
import semantic_ci  # noqa: E402


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_normalize_backend_accepts_known_values() -> None:
    for value in ("ollama", "yandex", "disabled", "OLLAMA", " Yandex "):
        assert semantic_ci.normalize_backend(value) in semantic_ci.KNOWN_BACKENDS


def test_normalize_backend_rejects_unknown() -> None:
    with pytest.raises(semantic_ci.UnknownBackendError):
        semantic_ci.normalize_backend("openai")
    with pytest.raises(semantic_ci.UnknownBackendError):
        semantic_ci.normalize_backend("")


def test_resolve_backend_prefers_cli_then_env() -> None:
    assert semantic_ci.resolve_backend(cli_provider="yandex", environ={}) == "yandex"
    assert (
        semantic_ci.resolve_backend(
            cli_provider=None,
            environ={"LLM_BACKEND": "ollama"},
        )
        == "ollama"
    )
    assert semantic_ci.resolve_backend(cli_provider=None, environ={}) == "disabled"


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (0, "ok"),
        (2, "formal_findings_ignored"),
        (3, "config_error_advisory"),
        (4, "tool_error_advisory"),
        (99, "advisory_exit_99"),
    ],
)
def test_normalize_advisory_exit_always_non_blocking(code: int, status: str) -> None:
    result = semantic_ci.normalize_advisory_exit(code, provider="ollama")
    assert result.status == status
    assert result.blocks_merge is False
    assert result.advisory is True
    assert result.process_exit == code


def test_disabled_provider_writes_valid_artifact_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("disabled backend must not call subprocess")

    monkeypatch.setattr(semantic_ci.subprocess, "run", fail_run)
    out = tmp_path / "semantic"
    result = semantic_ci.run_semantic_ci(provider="disabled", out_dir=out)
    assert result.status == "skipped"
    payload = json.loads((out / "status.json").read_text(encoding="utf-8"))
    assert payload["provider"] == "disabled"
    assert payload["status"] == "skipped"
    assert payload["blocks_merge"] is False
    assert payload["advisory"] is True


def test_warning_and_tool_error_normalized_to_successful_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_run(code: int):
        def _run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            calls.append(code)
            return subprocess.CompletedProcess(args=[], returncode=code)

        return _run

    out = tmp_path / "warn"
    monkeypatch.setattr(semantic_ci.subprocess, "run", fake_run(2))
    warn = semantic_ci.run_semantic_ci(provider="ollama", out_dir=out)
    assert warn.status == "formal_findings_ignored"
    assert json.loads((out / "status.json").read_text(encoding="utf-8"))["blocks_merge"] is False

    out2 = tmp_path / "tool"
    monkeypatch.setattr(semantic_ci.subprocess, "run", fake_run(4))
    tool = semantic_ci.run_semantic_ci(provider="ollama", out_dir=out2)
    assert tool.status == "tool_error_advisory"
    assert tool.blocks_merge is False
    assert calls == [2, 4]


def test_yandex_without_allow_cloud_skips_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        semantic_ci.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network")),
    )
    out = tmp_path / "cloud"
    result = semantic_ci.run_semantic_ci(
        provider="yandex",
        out_dir=out,
        allow_cloud_data=False,
    )
    assert result.status == "cloud_blocked"
    payload = json.loads((out / "status.json").read_text(encoding="utf-8"))
    assert payload["status"] == "cloud_blocked"


def test_main_unknown_backend_exits_one() -> None:
    code = semantic_ci.main(["--provider", "nope", "--out", str(ROOT / "build" / "tmp-bad")])
    assert code == 1


def test_workflow_has_no_pull_request_and_no_pull_request_target() -> None:
    payload = _load_workflow()
    triggers = payload.get("on", payload.get(True))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert payload["permissions"] == {"contents": "read"}


def test_ollama_job_requires_main_environment_and_self_hosted() -> None:
    payload = _load_workflow()
    job = payload["jobs"]["semantic-ollama"]
    assert job["runs-on"] == ["self-hosted", "windows", "x64", "gpu", "normocontrol"]
    assert job["environment"] == "local-gpu"
    assert "refs/heads/main" in str(job["if"])
    text = WORKFLOW.read_text(encoding="utf-8")
    ollama_section = text.split("semantic-ollama:")[1].split("semantic-yandex:")[0]
    assert "secrets.YANDEX_AI_API_KEY" not in ollama_section
    assert "${{ secrets." not in ollama_section
    assert "pull_request" not in ollama_section


def test_yandex_job_uses_cloud_environment_and_secret() -> None:
    payload = _load_workflow()
    job = payload["jobs"]["semantic-yandex"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["environment"] == "semantic-cloud"
    text = WORKFLOW.read_text(encoding="utf-8")
    yandex_section = text.split("semantic-yandex:")[1].split("semantic-disabled:")[0]
    assert "secrets.YANDEX_AI_API_KEY" in yandex_section
    assert "ALLOW_CLOUD_DATA" in yandex_section


def test_provider_jobs_are_mutually_exclusive() -> None:
    payload = _load_workflow()
    ollama_if = str(payload["jobs"]["semantic-ollama"]["if"])
    yandex_if = str(payload["jobs"]["semantic-yandex"]["if"])
    disabled_if = str(payload["jobs"]["semantic-disabled"]["if"])
    assert "ollama" in ollama_if
    assert "yandex" in yandex_if
    assert "disabled" in disabled_if
    assert ollama_if != yandex_if != disabled_if


def test_semantic_jobs_are_not_in_formal_required_set() -> None:
    formal = yaml.safe_load(FORMAL_WORKFLOW.read_text(encoding="utf-8"))
    formal_jobs = set(formal["jobs"])
    assert "semantic-ollama" not in formal_jobs
    assert "semantic-yandex" not in formal_jobs
    assert "semantic-disabled" not in formal_jobs
    assert "publish-semantic" not in formal_jobs
    assert "lint-and-unit" in formal_jobs
    assert "formal-gate" in formal_jobs


def test_checkout_uses_trusted_main_not_input_sha() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ref: main" in text
    assert "inputs.sha" not in text
    assert "github.event.inputs.sha" not in text


def test_ps1_disabled_invocation(tmp_path: Path) -> None:
    out = tmp_path / "ps1-out"
    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "semantic_ci.ps1"),
            "-Provider",
            "disabled",
            "-Out",
            str(out),
        ],
        check=False,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads((out / "status.json").read_text(encoding="utf-8"))
    assert payload["status"] == "skipped"
