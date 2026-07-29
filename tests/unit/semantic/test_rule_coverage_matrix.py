from __future__ import annotations

from collections import Counter
from pathlib import Path

from normocontrol.rubric.loader import load_rubric

ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "docs" / "rule-coverage.md"


def _matrix_rule_ids() -> list[str]:
    rows = MATRIX.read_text(encoding="utf-8").splitlines()
    return [
        cells[0]
        for line in rows
        if line.startswith("|")
        and (cells := [cell.strip() for cell in line.strip("|").split("|")])
        and cells[0] not in {"rule_id", "---"}
    ]


def test_rule_coverage_matrix_matches_every_rubric_rule_exactly_once() -> None:
    rubric_ids = [rule.id for rule in load_rubric(ROOT / "rubric.yaml").rules]
    matrix_ids = _matrix_rule_ids()
    counts = Counter(matrix_ids)

    assert len(rubric_ids) == 64
    assert len(matrix_ids) == 64
    assert set(matrix_ids) == set(rubric_ids)
    assert {rule_id: count for rule_id, count in counts.items() if count != 1} == {}
