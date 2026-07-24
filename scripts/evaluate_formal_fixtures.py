"""Evaluate annotated formal fixtures and print TP/FP/FN metrics."""

from __future__ import annotations

import argparse
from pathlib import Path

from normocontrol.evaluation.runner import evaluate_catalog_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "tests" / "fixtures" / "formal" / "catalog.yaml"
DEFAULT_RUBRIC = ROOT / "rubric.yaml"
DEFAULT_CONFIG = ROOT / "normocontrol.yaml.example"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()

    report = evaluate_catalog_file(
        args.catalog,
        repo_root=args.repo_root,
        rubric_path=args.rubric,
        config_path=args.config,
    )
    counts = report.counts
    print(f"labeled_pairs={report.labeled_pairs}")
    print(f"TP={counts.tp} FP={counts.fp} FN={counts.fn} TN={counts.tn}")
    print(f"precision={counts.precision:.3f} recall={counts.recall:.3f} f1={counts.f1:.3f}")
    if report.mismatches:
        print("mismatches:")
        for item in report.mismatches:
            actual = ", ".join(status.value for status in item.actual) or "none"
            print(f"  {item.fixture_id} {item.rule_id}: expected={item.expected} actual={actual}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
