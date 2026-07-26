"""Formal fixture catalog evaluation and TP/FP/FN metrics."""

from normocontrol.evaluation.catalog import FixtureCatalog, FixtureSpec, load_fixture_catalog
from normocontrol.evaluation.metrics import (
    ConfusionCounts,
    MetricMismatch,
    MetricReport,
    RuleMetric,
    compute_metrics,
)
from normocontrol.evaluation.runner import evaluate_catalog, evaluate_catalog_file, run_fixture

__all__ = [
    "ConfusionCounts",
    "FixtureCatalog",
    "FixtureSpec",
    "MetricMismatch",
    "MetricReport",
    "RuleMetric",
    "compute_metrics",
    "evaluate_catalog",
    "evaluate_catalog_file",
    "load_fixture_catalog",
    "run_fixture",
]
