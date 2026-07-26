from __future__ import annotations

import json
from pathlib import Path

from normocontrol.evaluation.semantic import SemanticEvaluationReport
from scripts.evaluate_semantic import main


def test_offline_evaluation_script_writes_reproducible_metrics(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first_code = main(["--provider", "mock", "--output", str(first_path)])
    second_code = main(["--provider", "mock", "--output", str(second_path)])

    assert first_code == second_code == 0
    assert first_path.read_bytes() == second_path.read_bytes()
    report = SemanticEvaluationReport.model_validate(
        json.loads(first_path.read_text(encoding="utf-8"))
    )
    assert all(item.schema_valid_rate == 1.0 for item in report.rules)
    assert all(item.evidence_valid_rate == 1.0 for item in report.rules)
    assert all(item.useful_advisory_rate == 1.0 for item in report.rules)
    assert report.schema_validity == 1.0
    assert report.evidence_validity == 1.0
    assert report.useful_advisory_rate == 1.0
    assert report.implemented_rule_count == 19
    assert report.not_implemented_rule_count == 6
    assert all(errors == () for errors in report.errors_by_rule_id.values())
