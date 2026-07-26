"""Integration tests for D-06 annotated fixtures and TP/FP/FN metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from normocontrol.domain import FindingStatus
from normocontrol.evaluation.catalog import load_fixture_catalog
from normocontrol.evaluation.runner import evaluate_catalog_file, run_fixture

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "tests" / "fixtures" / "formal" / "catalog.yaml"
RUBRIC = ROOT / "rubric.yaml"
CONFIG = ROOT / "normocontrol.yaml.example"


@pytest.fixture(scope="module")
def metric_report():
    if not CATALOG.is_file():
        pytest.skip("run scripts/generate_fixture_catalog.py first")
    return evaluate_catalog_file(
        CATALOG,
        repo_root=ROOT,
        rubric_path=RUBRIC,
        config_path=CONFIG,
    )


def test_catalog_has_zero_false_positives_and_false_negatives(metric_report) -> None:
    assert metric_report.counts.fp == 0, metric_report.mismatches
    assert metric_report.counts.fn == 0, metric_report.mismatches
    assert not metric_report.mismatches


def test_catalog_reports_perfect_recall_and_precision(metric_report) -> None:
    assert metric_report.counts.precision == 1.0
    assert metric_report.counts.recall == 1.0
    assert metric_report.counts.f1 == 1.0
    assert metric_report.labeled_pairs >= 80


@pytest.mark.parametrize(
    ("fixture_id", "rule_id", "expected_label", "expected_status"),
    [
        ("d05-bib-pass", "REV-02", "silent", FindingStatus.PASS),
        ("d05-fail-bib03", "BIB-03", "fail", FindingStatus.FAIL),
        ("d05-fail-bib04", "BIB-04", "fail", FindingStatus.FAIL),
        ("d05-fail-rev03", "REV-03", "warn", FindingStatus.WARN),
        ("d05-fail-rev04", "REV-04", "fail", FindingStatus.FAIL),
    ],
)
def test_d05_acceptance_mismatch_regressions(
    fixture_id: str,
    rule_id: str,
    expected_label: str,
    expected_status: FindingStatus,
) -> None:
    catalog = load_fixture_catalog(CATALOG)
    fixture = next(item for item in catalog.fixtures if item.id == fixture_id)

    assert fixture.labels[rule_id] == expected_label
    findings = run_fixture(
        fixture,
        repo_root=ROOT,
        rubric_path=RUBRIC,
        config_path=CONFIG,
    )
    statuses = tuple(item.status for item in findings if item.rule_id == rule_id)
    assert statuses == (expected_status,)
