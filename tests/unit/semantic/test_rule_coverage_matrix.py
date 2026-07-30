from __future__ import annotations

from collections import Counter
from pathlib import Path

from normocontrol.rubric.loader import load_rubric
from normocontrol.semantic.schemas import IMPLEMENTED_RULE_IDS, SEMANTIC_RULE_IDS

ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "docs" / "rule-coverage.md"
DECISION_DOC = ROOT / "docs" / "rule-decisions" / "ALG-02-IMP-02-DEP-01.md"
DECISION_DOC_REF = "docs/rule-decisions/ALG-02-IMP-02-DEP-01.md"

COLUMNS = ("rule_id", "layer", "implementation", "test", "status", "rationale")
MANUAL_ONLY_RULE_IDS = ("ALG-02", "IMP-02", "DEP-01")


def _matrix_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] in {"rule_id", "---"}:
            continue
        rows.append(dict(zip(COLUMNS, cells, strict=True)))
    return rows


def _matrix_rule_ids() -> list[str]:
    return [row["rule_id"] for row in _matrix_rows()]


def test_rule_coverage_matrix_matches_every_rubric_rule_exactly_once() -> None:
    rubric_ids = [rule.id for rule in load_rubric(ROOT / "rubric.yaml").rules]
    matrix_ids = _matrix_rule_ids()
    counts = Counter(matrix_ids)

    assert len(rubric_ids) == 64
    assert len(matrix_ids) == 64
    assert set(matrix_ids) == set(rubric_ids)
    assert {rule_id: count for rule_id, count in counts.items() if count != 1} == {}


def test_rule_coverage_matrix_row_order_is_deterministic() -> None:
    rubric_ids = [rule.id for rule in load_rubric(ROOT / "rubric.yaml").rules]

    assert _matrix_rule_ids() == rubric_ids


def test_rule_coverage_matrix_keeps_the_agreed_columns() -> None:
    lines = MATRIX.read_text(encoding="utf-8").splitlines()
    header = next(line for line in lines if line.startswith("|"))

    assert [cell.strip() for cell in header.strip("|").split("|")] == list(COLUMNS)


def test_manual_only_rules_are_recorded_as_manual_required() -> None:
    rows = {row["rule_id"]: row for row in _matrix_rows()}

    for rule_id in MANUAL_ONLY_RULE_IDS:
        row = rows[rule_id]
        assert row["layer"] == "manual"
        assert row["status"] == "manual_required"


def test_manual_required_rules_declare_no_automated_implementation() -> None:
    rows = {row["rule_id"]: row for row in _matrix_rows()}

    for rule_id in MANUAL_ONLY_RULE_IDS:
        row = rows[rule_id]
        assert "none" in row["implementation"].lower()
        for layer in ("formal", "semantic", "vision", "ocr"):
            assert layer not in row["implementation"].lower()
        assert "coverage matrix" in row["test"].lower()
        for layer in ("formal suite", "semantic suite", "vision"):
            assert layer not in row["test"].lower()


def test_manual_required_rules_reference_the_written_decision() -> None:
    rows = {row["rule_id"]: row for row in _matrix_rows()}

    for rule_id in MANUAL_ONLY_RULE_IDS:
        assert DECISION_DOC_REF in rows[rule_id]["rationale"]


def test_manual_required_is_neither_implemented_nor_pass() -> None:
    rows = {row["rule_id"]: row for row in _matrix_rows()}
    manual = {row["rule_id"] for row in rows.values() if row["status"] == "manual_required"}
    implemented = {row["rule_id"] for row in rows.values() if row["status"] == "implemented"}

    assert manual == set(MANUAL_ONLY_RULE_IDS)
    assert manual.isdisjoint(implemented)
    assert manual.isdisjoint(IMPLEMENTED_RULE_IDS)
    assert manual.isdisjoint(SEMANTIC_RULE_IDS)
    for rule_id in MANUAL_ONLY_RULE_IDS:
        assert "pass" not in rows[rule_id]["status"].lower()


def test_rule_coverage_matrix_has_no_pending_decision_left() -> None:
    statuses = Counter(row["status"] for row in _matrix_rows())

    assert statuses["pending_decision"] == 0
    assert statuses["implemented"] == 61
    assert statuses["manual_required"] == 3


def test_remaining_rules_stay_implemented_and_automated() -> None:
    rows = [row for row in _matrix_rows() if row["rule_id"] not in MANUAL_ONLY_RULE_IDS]

    assert len(rows) == 61
    for row in rows:
        assert row["status"] == "implemented"
        assert row["layer"] != "manual"
        assert row["implementation"] != "—"
        assert row["test"] != "—"
        assert row["rationale"]


def test_semantic_rule_inventory_is_unchanged_by_manual_required() -> None:
    assert len(SEMANTIC_RULE_IDS) == 25
    assert IMPLEMENTED_RULE_IDS == SEMANTIC_RULE_IDS
    assert not SEMANTIC_RULE_IDS - IMPLEMENTED_RULE_IDS
    assert set(MANUAL_ONLY_RULE_IDS).isdisjoint(SEMANTIC_RULE_IDS)


def test_written_decision_document_records_the_manual_only_scope() -> None:
    text = DECISION_DOC.read_text(encoding="utf-8")

    for rule_id in MANUAL_ONLY_RULE_IDS:
        assert f"`{rule_id}`: manual_required" in text
    assert "не является PASS" in text
    assert "formal gate" in text
    assert "exit code" in text
