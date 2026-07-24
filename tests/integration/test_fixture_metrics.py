"""Integration tests for D-06 annotated fixtures and TP/FP/FN metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from normocontrol.evaluation.runner import evaluate_catalog_file

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


def test_catalog_reports_perfect_recall_and_precision(metric_report) -> None:
    assert metric_report.counts.precision == 1.0
    assert metric_report.counts.recall == 1.0
    assert metric_report.counts.f1 == 1.0
    assert metric_report.labeled_pairs >= 80
