"""Output contract tests for the formal fixture evaluator."""

from __future__ import annotations

import sys

import pytest

from normocontrol.domain import FindingStatus
from normocontrol.evaluation.metrics import (
    ConfusionCounts,
    MetricMismatch,
    MetricReport,
    RuleMetric,
)
from scripts import evaluate_formal_fixtures


def test_script_groups_mismatches_by_rule_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mismatch = MetricMismatch(
        fixture_id="synthetic-fail",
        rule_id="STR-01",
        expected="fail",
        actual=(FindingStatus.PASS,),
    )
    rule = RuleMetric(
        rule_id="STR-01",
        expected=1,
        actual=0,
        counts=ConfusionCounts(tp=0, fp=0, fn=1, tn=0),
        unverifiable=0,
        not_applicable=0,
        mismatches=(mismatch,),
        labeled_pairs=1,
    )
    report = MetricReport(
        counts=rule.counts,
        mismatches=(mismatch,),
        labeled_pairs=1,
        per_rule=(rule,),
    )
    monkeypatch.setattr(
        evaluate_formal_fixtures,
        "evaluate_catalog_file",
        lambda *args, **kwargs: report,
    )
    monkeypatch.setattr(sys, "argv", ["evaluate_formal_fixtures.py"])

    exit_code = evaluate_formal_fixtures.main()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "STR-01 expected=1 actual=0 TP=0 FP=0 FN=1 TN=0" in output
    assert "mismatches_by_rule:\n  STR-01:\n" in output
    assert "synthetic-fail: expected=fail actual=pass" in output
