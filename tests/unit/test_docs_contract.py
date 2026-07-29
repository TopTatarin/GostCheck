"""Offline docs/release contract tests for A-06."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import release_check  # noqa: E402

REQUIRED_DOC_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE",
    "docs/architecture.md",
    "docs/setup-windows.md",
    "docs/setup-linux.md",
    "docs/troubleshooting.md",
    "docs/privacy.md",
    "docs/acceptance.md",
    "docs/source-submissions.md",
    ".github/dependabot.yml",
    ".github/CODEOWNERS",
    "scripts/release_check.py",
)

README_REQUIRED_HEADINGS = (
    "Быстрый старт",
    "Provider flags",
    "Коды выхода",
    "Архитектура",
    "Границы автоматизации",
)

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def test_required_docs_exist() -> None:
    missing = [path for path in REQUIRED_DOC_FILES if not (ROOT / path).is_file()]
    assert missing == [], f"missing docs: {missing}"


def test_readme_required_sections() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in README_REQUIRED_HEADINGS:
        assert heading in text, f"README missing section: {heading}"
    assert "lint-and-unit" in text or "formal-gate" in text
    assert "demo/pass" in text or "fixtures/demo/pass" in text


def test_security_and_acceptance_mention_branch_protection() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "docs" / "acceptance.md").read_text(encoding="utf-8")
    assert "formal-gate" in security
    assert "lint-and-unit" in security
    assert "semantic" in security.lower()
    assert "v0.1.0" in acceptance
    assert "git tag" in acceptance


def test_latex_gate_docs_match_hard_ci_contract() -> None:
    actions = (ROOT / "docs" / "github-actions.md").read_text(encoding="utf-8")
    setup = (ROOT / "docs" / "setup-linux.md").read_text(encoding="utf-8")
    troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")

    required_rows = {
        match.group(1)
        for match in re.finditer(
            r"^\|\s*`([^`]+)`\s*\|\s*\*\*yes\*\*\s*\|",
            actions,
            flags=re.MULTILINE,
        )
    }
    assert required_rows == {"lint-and-unit", "formal-gate"}
    assert 'install-tex: "true"' in actions
    assert "if: always()" in actions
    assert "Proprietary Times" in actions
    assert "not installed in CI." in actions

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
        assert package in setup
    assert "degraded success" in setup
    assert "unresolved reference" in troubleshooting
    assert "biber parse error" in troubleshooting
    assert "ChkTeX blocks formal-gate" in troubleshooting
    assert "Times New Roman absent on CI" in troubleshooting


def test_source_submission_contract_is_documented() -> None:
    contract = (ROOT / "docs" / "source-submissions.md").read_text(encoding="utf-8")
    windows = (ROOT / "docs" / "setup-windows.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "docs" / "acceptance.md").read_text(encoding="utf-8")

    for token in (
        "readable `.pdf`",
        "`main.tex`",
        "`--root`",
        "class/style",
        "bibliography",
        "images",
        "includes",
        "exit `2`",
        "exit `3`",
        "UNVERIFIABLE",
    ):
        assert token in contract
    for command in (
        "latexmk --version",
        "chktex --version",
        "xelatex --version",
        "biber --version",
    ):
        assert command in windows
    assert "Git Bash" in windows
    assert "PowerShell" in windows
    assert "GOSTCHECK_ACCEPTANCE_MISIS_SOURCE" in acceptance
    assert "GOSTCHECK_ACCEPTANCE_SALARY_SOURCE" in acceptance
    assert "GOSTCHECK_ACCEPTANCE_SECTIONS_SOURCE" in acceptance


def test_reusable_consumer_workflow_documentation_contract() -> None:
    actions = (ROOT / "docs" / "github-actions.md").read_text(encoding="utf-8")
    privacy = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")

    assert ".github/workflows/reusable-thesis.yml" in actions
    assert "workflow_call" in actions
    assert "TopTatarin/GostCheck/.github/workflows/reusable-thesis.yml@v0.2.0" in actions
    for item in (
        "submission_path: thesis/main.tex",
        "profile: software",
        "fail_closed: true",
        "upload_report: true",
        "provider: disabled",
        "contents: read",
        "pull-requests: write",
    ):
        assert item in actions
    assert "private repository" in actions
    assert "pinned commit SHA" in actions
    assert "pull_request_target" in actions
    assert "semantic" in actions.lower()
    assert "required" in actions.lower()

    assert "private thesis repository" in privacy
    assert "protected submission store" in privacy
    assert "public GostCheck repository" in privacy
    assert "symlink" in troubleshooting
    assert "submission_path" in troubleshooting


def test_local_markdown_links_resolve() -> None:
    """Relative repo links in key docs must point at existing files (no network)."""
    files = [
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "docs" / "architecture.md",
        ROOT / "docs" / "acceptance.md",
    ]
    broken: list[str] = []
    for doc in files:
        text = doc.read_text(encoding="utf-8")
        for _label, target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("#"):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (doc.parent / path_part).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                broken.append(f"{doc.name} -> {target} (outside repo)")
                continue
            if not resolved.exists():
                broken.append(f"{doc.name} -> {target}")
    assert broken == [], "broken local links:\n" + "\n".join(broken)


def test_release_check_mock_success(tmp_path: Path) -> None:
    out = tmp_path / "release-check.json"
    code = release_check.main(["--mock", "--out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["version"] == "0.1.0"
    assert [stage["name"] for stage in payload["stages"]] == list(release_check.STAGE_NAMES)


@pytest.mark.parametrize("stage", release_check.STAGE_NAMES)
def test_release_check_artificial_failure_each_stage(stage: str, tmp_path: Path) -> None:
    out = tmp_path / f"fail-{stage}.json"
    code = release_check.main(["--mock", "--fail-stage", stage, "--out", str(out)])
    assert code == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["stages"][-1]["name"] == stage
    assert payload["stages"][-1]["ok"] is False


def test_release_check_unknown_stage_raises() -> None:
    with pytest.raises(ValueError, match="unknown stages"):
        release_check.run_release_check(stages=("nope",), mock=True)  # type: ignore[arg-type]


def test_changelog_has_v010() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "0.1.0" in text


def test_no_tracked_private_pdf_or_home_secrets() -> None:
    """Fail if git index tracks private PDFs or real-looking secrets/home paths."""
    listed = subprocess.run(
        ["git", "ls-files"],
        check=True,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    offenders: list[str] = []
    for path in listed:
        norm = path.replace("\\", "/")
        lower = norm.lower()
        if lower.endswith(".pdf") and "tests/fixtures/pdf/" not in norm:
            offenders.append(path)
        if norm.startswith("samples/private/") and not norm.endswith((".gitkeep", ".gitignore")):
            offenders.append(path)
    assert offenders == [], f"tracked private/binary paths: {offenders}"

    # Real-looking secrets only. Placeholders like <secret> and synthetic
    # fingerprint fixtures under tests/ are allowed.
    api_key_pattern = re.compile(
        r"""(?x)
        (?:YANDEX_AI_API_KEY|LLM_API_KEY)\s*=\s*['\"]
        (?!<secret>|YOUR_|changeme|sk-unit)
        [^'\"]{12,}
        ['\"]
        """
    )
    home_pattern = re.compile(r"C:\\Users\\[A-Za-z][A-Za-z0-9_\-]{2,}\\")
    content_hits: list[str] = []
    for path in listed:
        norm = path.replace("\\", "/")
        if not path.endswith((".md", ".py", ".yml", ".yaml", ".json", ".toml", ".txt")):
            continue
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        if api_key_pattern.search(text):
            content_hits.append(f"{norm}:api-key")
        # Home paths in unit fixtures are intentional (fingerprint stability).
        if norm.startswith("tests/"):
            continue
        if home_pattern.search(text):
            content_hits.append(f"{norm}:home-path")
    assert content_hits == [], f"possible secrets/home paths in: {content_hits}"
