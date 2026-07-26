"""Unit tests for formal fixture metrics."""

from __future__ import annotations

from normocontrol.domain import FindingStatus
from normocontrol.evaluation.metrics import (
    ConfusionCounts,
    compute_metrics,
    expectation_matches,
)


def test_expectation_matches_silent_and_fail() -> None:
    assert expectation_matches((FindingStatus.PASS,), "silent")
    assert not expectation_matches((FindingStatus.FAIL,), "silent")
    assert expectation_matches((FindingStatus.FAIL,), "fail")


def test_compute_metrics_counts_tp_fp_fn() -> None:
    observations = (
        ("f1", "R1", "fail", (FindingStatus.FAIL,)),
        ("f2", "R1", "silent", (FindingStatus.PASS,)),
        ("f3", "R1", "fail", (FindingStatus.PASS,)),
        ("f4", "R1", "silent", (FindingStatus.WARN,)),
    )
    report = compute_metrics(observations)
    assert report.counts.tp == 1
    assert report.counts.fn == 1
    assert report.counts.fp == 1
    assert report.counts.tn == 1
    assert len(report.mismatches) == 2


def test_zero_denominators_are_reported_as_zero() -> None:
    counts = ConfusionCounts(tp=0, fp=0, fn=0, tn=0)

    assert counts.precision == 0.0
    assert counts.recall == 0.0
    assert counts.f1 == 0.0


def test_per_rule_metrics_include_outcomes_mismatches_and_absent_rule() -> None:
    observations = (
        ("positive", "STR-01", "fail", (FindingStatus.FAIL,)),
        ("incomplete", "STR-01", "silent", (FindingStatus.UNVERIFIABLE,)),
        ("false-negative", "FMT-01", "fail", (FindingStatus.NOT_APPLICABLE,)),
    )

    report = compute_metrics(
        observations,
        rule_ids=("STR-01", "FMT-01", "APP-01"),
    )
    by_rule = {item.rule_id: item for item in report.per_rule}

    structural = by_rule["STR-01"]
    assert structural.expected == 1
    assert structural.actual == 1
    assert structural.counts == ConfusionCounts(tp=1, fp=0, fn=0, tn=1)
    assert structural.unverifiable == 1
    assert structural.not_applicable == 0
    assert structural.mismatches == ()

    formatting = by_rule["FMT-01"]
    assert formatting.expected == 1
    assert formatting.actual == 0
    assert formatting.counts.fn == 1
    assert formatting.not_applicable == 1
    assert formatting.mismatches[0].fixture_id == "false-negative"

    absent = by_rule["APP-01"]
    assert absent.expected == 0
    assert absent.actual == 0
    assert absent.counts == ConfusionCounts(tp=0, fp=0, fn=0, tn=0)
    assert absent.counts.precision == 0.0
    assert absent.counts.recall == 0.0
    assert absent.counts.f1 == 0.0
    assert absent.mismatches == ()
