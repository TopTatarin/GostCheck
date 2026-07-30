"""Integration coverage for the advisory formal gate mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from normocontrol.domain import ExitCode, GateMode
from normocontrol.orchestrator import run_pipeline
from normocontrol.reporting.json_report import load_report_schema, validate_published_report
from normocontrol.run_context import RunRequest, parse_only

ROOT = Path(__file__).resolve().parents[2]
PDF_FIXTURES = ROOT / "tests" / "fixtures" / "pdf"
RUBRIC_PATH = ROOT / "rubric.yaml"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"
# ``fmt_pass.pdf`` has no proven violation but leaves class-layer rules unverifiable.
UNVERIFIABLE_PDF = PDF_FIXTURES / "fmt_pass.pdf"
FAILING_PDF = PDF_FIXTURES / "fmt_wrong_font.pdf"


def _config_with_gate_mode(tmp_path: Path, gate_mode: str) -> Path:
    """Copy the shipped example and set only ``gate_mode``."""
    source = CONFIG_PATH.read_text(encoding="utf-8")
    lines = [line for line in source.splitlines() if not line.startswith("gate_mode:")]
    path = tmp_path / "normocontrol.yaml"
    path.write_text("\n".join([*lines, f"gate_mode: {gate_mode}"]) + "\n", encoding="utf-8")
    return path


def _stages_without_timing(published: dict[str, Any]) -> list[dict[str, Any]]:
    """Drop wall-clock timings so two runs stay comparable."""
    return [
        {key: value for key, value in stage.items() if key != "duration_ms"}
        for stage in published["stages"]
    ]


def _run(
    tmp_path: Path,
    *,
    name: str,
    source: Path = UNVERIFIABLE_PDF,
    gate_mode: GateMode | None = None,
    config_path: Path = CONFIG_PATH,
    only: str | None = None,
) -> tuple[ExitCode, dict[str, Any]]:
    out_dir = tmp_path / name
    report = run_pipeline(
        RunRequest(
            source=source,
            out_dir=out_dir,
            config_path=config_path,
            rubric_path=RUBRIC_PATH,
            no_llm=True,
            gate_mode=gate_mode,
            only=parse_only((only,) if only else None),
        )
    )
    published = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert isinstance(published, dict)
    return report.exit_code, published


def test_strict_default_still_blocks_on_unverifiable(tmp_path: Path) -> None:
    """Regression: no gate mode requested means strict."""
    exit_code, published = _run(tmp_path, name="strict")

    assert exit_code is ExitCode.FORMAL_FAILURE
    assert published["exit_code"] == 2
    assert published["header"]["gate_status"] == "fail"
    assert published["header"]["gate_mode"] == "strict"
    assert published["counts"]["blocking_unverifiable"] > 0
    assert published["counts"]["formal_errors"] == 0
    validate_published_report(published, schema=load_report_schema())


def test_advisory_does_not_block_on_unverifiable(tmp_path: Path) -> None:
    exit_code, published = _run(tmp_path, name="advisory", gate_mode=GateMode.ADVISORY)

    assert exit_code is ExitCode.SUCCESS
    assert published["exit_code"] == 0
    assert published["header"]["gate_status"] == "degraded"
    assert published["header"]["gate_mode"] == "advisory"
    validate_published_report(published, schema=load_report_schema())


def test_advisory_preserves_counts_findings_and_header_flags(tmp_path: Path) -> None:
    strict_code, strict = _run(tmp_path, name="strict")
    advisory_code, advisory = _run(tmp_path, name="advisory", gate_mode=GateMode.ADVISORY)

    assert strict_code is ExitCode.FORMAL_FAILURE
    assert advisory_code is ExitCode.SUCCESS
    # Advisory changes the decision, never the evidence.
    assert advisory["counts"] == strict["counts"]
    assert advisory["counts"]["blocking_unverifiable"] > 0
    assert sorted(item["rule_id"] for item in advisory["findings"]) == sorted(
        item["rule_id"] for item in strict["findings"]
    )
    assert advisory["header"]["degraded"] is True
    assert advisory["header"]["degraded"] == strict["header"]["degraded"]
    assert advisory["header"]["approvals_required"] == strict["header"]["approvals_required"]
    assert _stages_without_timing(advisory) == _stages_without_timing(strict)


def test_advisory_still_blocks_on_proven_failure(tmp_path: Path) -> None:
    exit_code, published = _run(
        tmp_path,
        name="advisory-fail",
        source=FAILING_PDF,
        gate_mode=GateMode.ADVISORY,
        only="FMT-01",
    )

    assert exit_code is ExitCode.FORMAL_FAILURE
    assert published["header"]["gate_status"] == "fail"
    assert published["header"]["gate_mode"] == "advisory"
    assert published["counts"]["formal_errors"] > 0
    validate_published_report(published, schema=load_report_schema())


def test_semantic_advisory_findings_never_block_in_either_mode(tmp_path: Path) -> None:
    """Advisory llm findings are reported but stay outside the formal gate."""
    for mode in (GateMode.STRICT, GateMode.ADVISORY):
        _, published = _run(
            tmp_path,
            name=f"llm-{mode.value}",
            source=UNVERIFIABLE_PDF,
            gate_mode=mode,
            only="ANN",
        )
        assert published["counts"]["formal_errors"] == 0
        assert published["header"]["gate_mode"] == mode.value
        assert all(
            item["layer"] not in {"llm", "vision"} or item["status"] != "fail"
            for item in published["findings"]
        )


@pytest.mark.parametrize(
    ("config_mode", "cli_mode", "expected_mode", "expected_exit"),
    [
        ("advisory", None, "advisory", ExitCode.SUCCESS),
        ("strict", None, "strict", ExitCode.FORMAL_FAILURE),
        # CLI wins over configuration in both directions.
        ("advisory", GateMode.STRICT, "strict", ExitCode.FORMAL_FAILURE),
        ("strict", GateMode.ADVISORY, "advisory", ExitCode.SUCCESS),
    ],
)
def test_cli_gate_mode_overrides_configuration(
    tmp_path: Path,
    config_mode: str,
    cli_mode: GateMode | None,
    expected_mode: str,
    expected_exit: ExitCode,
) -> None:
    config_path = _config_with_gate_mode(tmp_path, config_mode)
    name = f"{config_mode}-{cli_mode.value if cli_mode else 'none'}"

    exit_code, published = _run(
        tmp_path,
        name=name,
        gate_mode=cli_mode,
        config_path=config_path,
    )

    assert exit_code is expected_exit
    assert published["header"]["gate_mode"] == expected_mode
    validate_published_report(published, schema=load_report_schema())
