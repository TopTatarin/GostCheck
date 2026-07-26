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
    print("per_rule:")
    for item in report.per_rule:
        rule_counts = item.counts
        print(
            f"  {item.rule_id} expected={item.expected} actual={item.actual} "
            f"TP={rule_counts.tp} FP={rule_counts.fp} "
            f"FN={rule_counts.fn} TN={rule_counts.tn} "
            f"precision={rule_counts.precision:.3f} "
            f"recall={rule_counts.recall:.3f} f1={rule_counts.f1:.3f} "
            f"unverifiable={item.unverifiable} "
            f"not_applicable={item.not_applicable} "
            f"mismatches={len(item.mismatches)}"
        )
    print("mismatches_by_rule:")
    if report.mismatches:
        for rule in report.per_rule:
            if not rule.mismatches:
                continue
            print(f"  {rule.rule_id}:")
            for item in rule.mismatches:
                actual = ", ".join(status.value for status in item.actual) or "none"
                print(f"    {item.fixture_id}: expected={item.expected} actual={actual}")
        return 1
    print("  none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
