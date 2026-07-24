"""Unit tests for formal fixture metrics."""

from __future__ import annotations

from normocontrol.domain import FindingStatus
from normocontrol.evaluation.metrics import compute_metrics, expectation_matches


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
