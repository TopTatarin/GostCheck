from __future__ import annotations

import json

from typer.testing import CliRunner

from normocontrol.cli import app
from normocontrol.semantic.schemas import DiagnosticCode, SemanticReport

runner = CliRunner()


def test_semantic_cli_disabled_is_offline_deterministic_and_successful() -> None:
    args = [
        "semantic",
        "tests/fixtures/semantic/complete/bundle.json",
        "--provider",
        "disabled",
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0
    assert first.stdout == second.stdout
    report = SemanticReport.model_validate(json.loads(first.stdout))
    annotation = next(item for item in report.findings if item.rule_id == "ANN-01")
    assert annotation.diagnostic is DiagnosticCode.PROVIDER_DISABLED
    assert all(item.status.value != "fail" for item in report.findings)
