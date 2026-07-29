"""Static checks for the Normocontrol GitHub Actions workflow."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import normocontrol.cli as cli
from normocontrol.orchestrator import OrchestratorHooks, run_pipeline
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "normocontrol.yml"
REUSABLE_WORKFLOW = ROOT / ".github" / "workflows" / "reusable-thesis.yml"
SETUP_ACTION = ROOT / ".github" / "actions" / "setup-normocontrol" / "action.yml"
GITHUB_ACTIONS_DOC = ROOT / "docs" / "github-actions.md"
LATEX_FIXTURES = ROOT / "tests" / "fixtures" / "latex-ci"
REQUIRED_JOBS = ("lint-and-unit", "formal-gate")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _job_steps(job: dict) -> list[dict]:
    return job["steps"]


def _step_by_name(job: dict, name: str) -> dict:
    return next(step for step in _job_steps(job) if step.get("name") == name)


def test_workflow_yaml_parses_and_required_job_names() -> None:
    payload = _load_yaml(WORKFLOW)
    assert payload["name"] == "Normocontrol"
    jobs = payload["jobs"]
    assert set(REQUIRED_JOBS) == {"lint-and-unit", "formal-gate"}
    assert set(REQUIRED_JOBS).issubset(jobs)
    assert jobs["lint-and-unit"]["name"] == "lint-and-unit"
    assert jobs["formal-gate"]["name"] == "formal-gate"
    assert jobs["formal-gate"]["needs"] == ["lint-and-unit"]
    assert jobs["publish-report"]["name"] == "publish-report"
    assert jobs["build-latex"]["name"] == "build-latex"
    assert "semantic" not in jobs
    assert "semantic-advisory" not in jobs
    required_rows = {
        match.group(1)
        for match in re.finditer(
            r"^\|\s*`([^`]+)`\s*\|\s*\*\*yes\*\*\s*\|",
            GITHUB_ACTIONS_DOC.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    }
    assert required_rows == set(REQUIRED_JOBS)


def test_workflow_permissions_and_triggers() -> None:
    payload = _load_yaml(WORKFLOW)
    # PyYAML 1.1 parses bare key `on` as boolean True.
    triggers = payload.get("on", payload.get(True))
    assert triggers is not None
    assert "pull_request" in triggers
    assert "workflow_dispatch" in triggers
    assert "pull_request_target" not in triggers
    assert payload["permissions"] == {"contents": "read"}
    publish_perms = payload["jobs"]["publish-report"]["permissions"]
    assert publish_perms["pull-requests"] == "write"
    assert publish_perms["contents"] == "read"


def test_reusable_workflow_call_inputs_are_typed_and_safe() -> None:
    payload = _load_yaml(REUSABLE_WORKFLOW)
    triggers = payload.get("on", payload.get(True))
    assert set(triggers) == {"workflow_call"}
    inputs = triggers["workflow_call"]["inputs"]
    assert inputs["submission_path"] == {
        "description": (
            "Relative path to a LaTeX project, .tex file, or PDF in the caller repository"
        ),
        "required": True,
        "type": "string",
    }
    assert inputs["profile"]["type"] == "string"
    assert inputs["profile"]["default"] == "software"
    assert inputs["fail_closed"]["type"] == "boolean"
    assert inputs["fail_closed"]["default"] is True
    assert inputs["upload_report"]["type"] == "boolean"
    assert inputs["upload_report"]["default"] is True
    assert inputs["provider"]["type"] == "string"
    assert inputs["provider"]["default"] == "disabled"
    assert "pull_request_target" not in triggers


def test_reusable_workflow_has_minimal_permissions_and_separate_self_tests() -> None:
    reusable = _load_yaml(REUSABLE_WORKFLOW)
    assert reusable["permissions"] == {"contents": "read"}
    publish = reusable["jobs"]["publish-report"]
    assert publish["permissions"] == {"pull-requests": "write"}
    assert _load_yaml(WORKFLOW)["name"] == "Normocontrol"
    assert "workflow_call" not in (_load_yaml(WORKFLOW).get("on", _load_yaml(WORKFLOW).get(True)))
    engine_checkouts = [
        step
        for job in reusable["jobs"].values()
        for step in job["steps"]
        if step.get("name") == "Checkout pinned GostCheck implementation"
    ]
    assert len(engine_checkouts) == 3
    assert all(
        step["with"]["repository"] == "${{ job.workflow_repository }}"
        and step["with"]["ref"] == "${{ job.workflow_sha }}"
        and step["with"]["persist-credentials"] is False
        for step in engine_checkouts
    )


def test_reusable_formal_gate_uses_requested_submission() -> None:
    payload = _load_yaml(REUSABLE_WORKFLOW)
    jobs = payload["jobs"]
    formal = jobs["formal-gate"]
    assert formal["needs"] == ["lint-and-unit"]
    assert "semantic" not in formal["needs"]
    semantic = jobs["semantic-advisory"]
    assert semantic["needs"] == ["lint-and-unit"]
    assert semantic["continue-on-error"] is True
    assert "formal-gate" not in semantic["needs"]

    validate = _step_by_name(formal, "Revalidate submission path")
    assert validate["env"]["SUBMISSION_PATH"] == "${{ inputs.submission_path }}"
    run = _step_by_name(formal, "Run formal gate on requested submission")
    script = run["run"]
    assert 'run "$GITHUB_WORKSPACE/consumer/$SUBMISSION_RELATIVE"' in script
    assert '--profile "$PROFILE"' in script
    assert "--no-llm" in script
    assert "--only formal" in script
    assert "--only aggregate" in script
    assert "--provider" not in script
    assert "tests/fixtures/demo/pass" not in script
    assert "tests/fixtures/demo/fail" not in script

    semantic_script = _step_by_name(semantic, "Run non-blocking semantic checks")["run"]
    assert '--provider "$PROVIDER"' in semantic_script
    assert "--only semantic" in semantic_script


def test_reusable_artifact_excludes_consumer_source_and_pdf() -> None:
    payload = _load_yaml(REUSABLE_WORKFLOW)
    upload = _step_by_name(
        payload["jobs"]["formal-gate"],
        "Upload reports and technical logs",
    )
    paths = upload["with"]["path"].splitlines()
    assert "build/normocontrol/report.json" in paths
    assert "build/normocontrol/report.md" in paths
    assert "build/normocontrol/technical.log" in paths
    assert all("consumer/" not in path for path in paths)
    assert all(not path.casefold().endswith((".pdf", ".tex")) for path in paths)
    assert upload["if"] == "${{ always() && inputs.upload_report }}"


def test_reusable_comment_is_metadata_only_and_names_actual_input() -> None:
    payload = _load_yaml(REUSABLE_WORKFLOW)
    publish = payload["jobs"]["publish-report"]
    comment = _step_by_name(publish, "Publish or refresh metadata-only PR comment")
    env = comment["env"]
    assert "needs.formal-gate.outputs.submission_path" in env["CHECKED_PATH"]
    assert "inputs.submission_path" in env["CHECKED_PATH"]
    assert env["COMMIT_SHA"] == "${{ github.sha }}"
    assert env["PROFILE"] == "${{ inputs.profile }}"
    assert "${{ github.run_id }}" in env["RUN_URL"]
    script = comment["with"]["script"]
    for label in ("Checked path", "Commit SHA", "Profile", "Gate", "Run"):
        assert label in script
    assert "report.md" not in script
    assert "summary.json" not in script


def test_reusable_workflow_does_not_echo_secrets_or_source_content() -> None:
    text = REUSABLE_WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "echo ${{" not in text
    assert "pull_request_target" not in text
    assert "cat $SUBMISSION" not in text
    assert "tee " not in text


def test_every_uploaded_artifact_uses_always() -> None:
    payload = _load_yaml(WORKFLOW)
    uploads = [
        step
        for job in payload["jobs"].values()
        for step in _job_steps(job)
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert uploads
    assert all(step.get("if") == "always()" for step in uploads)


def test_latexmk_cannot_be_soft_failed_or_degraded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    logical_lines = re.sub(r"\\\s*\n\s*", " ", text)
    assert re.search(r"\blatexmk\b", logical_lines)
    assert not re.search(r"\blatexmk\b[^\n]*\|\|\s*true", logical_lines)
    assert "tool_missing" not in text
    assert "marking degraded" not in text


def test_setup_installs_and_verifies_minimal_tex_toolchain() -> None:
    payload = _load_yaml(SETUP_ACTION)
    assert payload["inputs"]["install-python"]["default"] == "true"
    assert payload["inputs"]["install-tex"]["default"] == "false"
    assert payload["inputs"]["project-root"]["default"] == "."
    dependencies = next(
        step for step in payload["runs"]["steps"] if step["name"] == "Install locked dependencies"
    )
    assert dependencies["env"]["PROJECT_ROOT"] == "${{ inputs.project-root }}"
    assert "${{ inputs.project-root }}" not in dependencies["run"]
    install = next(
        step for step in payload["runs"]["steps"] if step["name"] == "Install TeX toolchain"
    )
    script = install["run"]
    for package in (
        "latexmk",
        "chktex",
        "texlive-xetex",
        "biber",
        "fonts-freefont-ttf",
        "texlive-bibtex-extra",
        "texlive-lang-cyrillic",
        "fonts-texgyre",
    ):
        assert package in script
    for executable in ("latexmk", "chktex", "xelatex", "biber"):
        assert f"command -v {executable}" in script
    assert "kpsewhich biblatex-gost.def" in script
    assert "kpsewhich gost-numeric.bbx" in script
    assert 'fc-match "FreeMono" | grep -F "FreeMono"' in script
    assert 'fc-match "FreeSans" | grep -F "FreeSans"' in script
    assert 'fc-match "FreeSerif" | grep -F "FreeSerif"' in script
    assert 'fc-match "TeX Gyre Termes" | grep -F "TeX Gyre Termes"' in script
    assert "ttf-mscorefonts-installer" not in script
    assert "msttcorefonts" not in script

    workflow = _load_yaml(WORKFLOW)
    assert workflow["jobs"]["build-latex"]["runs-on"] == "ubuntu-24.04"
    build_setup = _step_by_name(workflow["jobs"]["build-latex"], "Setup normocontrol")
    assert build_setup["with"] == {
        "install-python": "false",
        "install-tex": "true",
    }
    formal = workflow["jobs"]["formal-gate"]
    assert formal["runs-on"] == "ubuntu-24.04"
    tex_setup = _step_by_name(formal, "Setup mandatory TeX toolchain")
    assert tex_setup["with"] == {
        "install-python": "false",
        "install-tex": "true",
    }
    formal_step_names = [step["name"] for step in _job_steps(formal)]
    assert formal_step_names.index("Formal gate on pass fixture") < formal_step_names.index(
        "Setup mandatory TeX toolchain"
    )
    assert formal_step_names.index("Setup mandatory TeX toolchain") < formal_step_names.index(
        "Compile and validate synthetic LaTeX fixtures"
    )
    lint_setup = _step_by_name(workflow["jobs"]["lint-and-unit"], "Setup normocontrol")
    assert "with" not in lint_setup


def test_formal_gate_proves_compile_reference_biber_and_chktex_contracts() -> None:
    formal = _load_yaml(WORKFLOW)["jobs"]["formal-gate"]
    compile_script = _step_by_name(formal, "Compile and validate synthetic LaTeX fixtures")["run"]
    assert "latexmk -xelatex -Werror" in compile_script
    assert "test -s build/latex/formal-pass/main.bbl" in compile_script
    assert "There were undefined references" in compile_script
    assert "compile-fail" in compile_script
    assert "unresolved-reference" in compile_script
    assert "biber-fail" in compile_script

    chktex_script = _step_by_name(formal, "Run blocking ChkTeX checks")["run"]
    assert "chktex -q" in chktex_script
    assert "chktex-fail" in chktex_script
    assert "blocking ChkTeX fixture unexpectedly passed" in chktex_script


def test_synthetic_latex_fixtures_cover_ci_corner_cases() -> None:
    pass_dir = LATEX_FIXTURES / "compile-pass" / "source with spaces"
    cls = (pass_dir / "gostcheck-vkr.cls").read_text(encoding="utf-8")
    main = (pass_dir / "main.tex").read_text(encoding="utf-8")
    assert r"\IfFontExistsTF{Times New Roman}" in cls
    assert r"\setmainfont{Times New Roman}" in cls
    assert r"\setmainfont{TeX Gyre Termes}" in cls
    assert r"\newfontfamily\cyrillicfont{FreeSerif}" in cls
    assert r"\newfontfamily\cyrillicfontsf{FreeSans}" in cls
    assert r"\newfontfamily\cyrillicfonttt{FreeMono}" in cls
    assert r"\setdefaultlanguage{russian}" in cls
    assert r"\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex}" in cls
    assert "Synthetic non-blocking warning" in cls
    assert "полностью синтетический текст" in main
    assert r"\ref{sec:introduction}" in main
    assert r"\autocite{synthetic-standard}" in main
    assert "\\printbibliography%\n" in main
    assert (pass_dir / "refs.bib").is_file()

    compile_fail = (LATEX_FIXTURES / "compile-fail" / "main.tex").read_text(encoding="utf-8")
    unresolved = (LATEX_FIXTURES / "unresolved-reference" / "main.tex").read_text(encoding="utf-8")
    chktex_fail = (LATEX_FIXTURES / "chktex-fail" / "main.tex").read_text(encoding="utf-8")
    biber_fail = (LATEX_FIXTURES / "biber-fail" / "refs.bib").read_text(encoding="utf-8")
    assert "gostcheck-intentionally-missing" in compile_fail
    assert r"\ref{sec:does-not-exist}" in unresolved
    assert r"\LaTeX is" in chktex_fail
    assert biber_fail.count("{") > biber_fail.count("}")


@pytest.mark.parametrize("fixture", ("pass", "fail"))
def test_demo_class_preserves_times_requirement_with_ci_fallback(fixture: str) -> None:
    fixture_dir = ROOT / "tests" / "fixtures" / "demo" / fixture
    cls = (fixture_dir / "gostcheck-vkr.cls").read_text(encoding="utf-8")
    assert r"\IfFontExistsTF{Times New Roman}" in cls
    assert r"\setmainfont{Times New Roman}" in cls
    assert r"\setmainfont{TeX Gyre Termes}" in cls
    assert r"\newfontfamily\cyrillicfont{FreeSerif}" in cls
    assert r"\newfontfamily\cyrillicfontsf{FreeSans}" in cls
    assert r"\newfontfamily\cyrillicfonttt{FreeMono}" in cls
    assert r"\setdefaultlanguage{russian}" in cls
    assert r"\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex}" in cls
    assert (fixture_dir / "latexmkrc").read_text(encoding="utf-8") == "$pdf_mode = 5;\n"


def test_local_formal_exit_two_leaves_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate the formal-gate fail path: exit 2 still produces report files."""

    class _SuccessBuild(LatexBuildService):
        def build(self, project_root: Path, main_tex: Path) -> LatexBuildResult:
            del project_root, main_tex
            return LatexBuildResult(
                status=LatexBuildStatus.SUCCESS,
                returncode=0,
                log_excerpt="mock",
            )

    def fake_pipeline(request, hooks=None):  # type: ignore[no-untyped-def]
        del hooks
        return run_pipeline(request, OrchestratorHooks(build_service=_SuccessBuild()))

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    out = tmp_path / "fail"
    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            str(ROOT / "tests" / "fixtures" / "demo" / "fail"),
            "--no-llm",
            "--config",
            str(ROOT / "normocontrol.yaml.example"),
            "--rubric",
            str(ROOT / "rubric.yaml"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 2
    assert (out / "report.json").is_file()
    assert (out / "report.md").is_file()
    assert (out / "summary.json").is_file()
