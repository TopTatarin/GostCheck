"""Tests for the deterministic formal rule engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from normocontrol.domain import Finding, FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import Capability
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.base import RuleExecutionError
from normocontrol.rules.context import SourceKind
from normocontrol.rules.engine import (
    EngineStateError,
    FormalEngine,
    RunMode,
    dedupe_findings,
    finding_fingerprint,
    serialize_findings,
)
from normocontrol.rules.registry import DuplicateRuleError, RuleRegistry

from .helpers import (
    StubFormalRule,
    effective_rule,
    execution_context,
    formal_fail,
    latex_bundle,
    latex_project,
    minimal_rubric,
    pdf_bundle,
)


def test_empty_rubric_produces_no_findings() -> None:
    rubric = minimal_rubric()
    context = execution_context(rubric, bundle=latex_bundle())
    result = FormalEngine(RuleRegistry()).run(context)

    assert result.findings == ()
    assert result.exit_code == 0


def test_registry_rejects_duplicate_rule_ids() -> None:
    registry = RuleRegistry()
    rule = StubFormalRule("SYS-01", frozenset({SourceKind.LATEX_PROJECT}))
    registry.register(rule)

    with pytest.raises(DuplicateRuleError, match="duplicate rule id"):
        registry.register(rule)


def test_missing_implementation_is_unverifiable_not_pass() -> None:
    rubric = minimal_rubric(effective_rule("SYS-01"))
    context = execution_context(rubric, bundle=latex_bundle())
    result = FormalEngine(RuleRegistry()).run(context)

    assert len(result.findings) == 1
    assert result.findings[0].status is FindingStatus.UNVERIFIABLE
    assert result.findings[0].rule_id == "SYS-01"


def test_unsupported_registration_is_unverifiable() -> None:
    registry = RuleRegistry()
    registry.mark_unsupported("SYS-01", reason="pending D-02")
    rubric = minimal_rubric(effective_rule("SYS-01"))
    context = execution_context(rubric, bundle=latex_bundle())
    result = FormalEngine(registry).run(context)

    assert result.findings[0].status is FindingStatus.UNVERIFIABLE
    assert "unsupported" in result.findings[0].message


def test_supports_false_yields_not_applicable() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "SYS-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            applicable=False,
        )
    )
    rubric = minimal_rubric(effective_rule("SYS-01"))
    context = execution_context(
        rubric,
        bundle=latex_bundle(),
        latex=latex_project(),
    )
    result = FormalEngine(registry).run(context)

    assert result.findings[0].status is FindingStatus.NOT_APPLICABLE


def test_pdf_only_marks_latex_required_rules_unverifiable() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "BIB-01",
            frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES}),
            findings=(formal_fail("BIB-01"),),
        )
    )
    rubric = minimal_rubric(effective_rule("BIB-01"))
    context = execution_context(rubric, bundle=pdf_bundle())
    result = FormalEngine(registry).run(context)

    assert result.findings[0].status is FindingStatus.UNVERIFIABLE
    assert "required source unavailable" in result.findings[0].message


def test_expected_rule_execution_error_respects_fail_closed() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "SYS-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            error=RuleExecutionError("latexmk failed"),
        )
    )
    rubric = minimal_rubric(effective_rule("SYS-01"))
    latex = latex_project()
    context_open = execution_context(rubric, bundle=latex_bundle(), latex=latex, fail_closed=False)
    context_closed = execution_context(rubric, bundle=latex_bundle(), latex=latex, fail_closed=True)

    open_result = FormalEngine(registry).run(context_open)
    closed_result = FormalEngine(registry).run(context_closed)

    assert open_result.findings[0].status is FindingStatus.UNVERIFIABLE
    assert open_result.exit_code == 0
    assert closed_result.findings[0].status is FindingStatus.FAIL
    assert closed_result.exit_code == 2


def test_unexpected_rule_error_is_isolated() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "SYS-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            error=RuntimeError("broken cache"),
        )
    )
    rubric = minimal_rubric(effective_rule("SYS-01"))
    result = FormalEngine(registry).run(
        execution_context(
            rubric,
            bundle=latex_bundle(),
            latex=latex_project(),
            fail_closed=True,
        )
    )

    assert "tool_error" in result.findings[0].message
    assert result.exit_code == 2


def test_canceled_run_raises() -> None:
    rubric = minimal_rubric(effective_rule("SYS-01"))
    context = execution_context(rubric, bundle=latex_bundle(), canceled=True)

    with pytest.raises(EngineStateError, match="canceled"):
        FormalEngine(RuleRegistry()).run(context)


def test_parallel_and_sequential_outputs_match() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "SYS-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            findings=(formal_fail("SYS-01", layer=RuleLayer.CLASS),),
        )
    )
    registry.register(
        StubFormalRule(
            "STR-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            findings=(
                Finding(
                    rule_id="STR-01",
                    layer=RuleLayer.SCRIPT,
                    severity=Severity.WARN,
                    status=FindingStatus.WARN,
                    message="section length warning",
                ),
            ),
        )
    )
    rubric = minimal_rubric(
        effective_rule("SYS-01", layer="class", capabilities=(Capability.CLASS,)),
        effective_rule("STR-01"),
    )
    context = execution_context(rubric, bundle=latex_bundle(), latex=latex_project())

    sequential = FormalEngine(registry).run(context, mode=RunMode.SEQUENTIAL)
    parallel = FormalEngine(registry).run(context, mode=RunMode.PARALLEL)

    assert serialize_findings(sequential.findings) == serialize_findings(parallel.findings)
    assert json.dumps(serialize_findings(sequential.findings), sort_keys=True) == json.dumps(
        serialize_findings(parallel.findings),
        sort_keys=True,
    )


def test_findings_sorted_by_rubric_order_locator_and_fingerprint() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "STR-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            findings=(
                Finding(
                    rule_id="STR-01",
                    layer=RuleLayer.SCRIPT,
                    severity=Severity.ERROR,
                    status=FindingStatus.FAIL,
                    message="second",
                ),
            ),
        )
    )
    registry.register(
        StubFormalRule(
            "SYS-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            findings=(
                Finding(
                    rule_id="SYS-01",
                    layer=RuleLayer.SCRIPT,
                    severity=Severity.ERROR,
                    status=FindingStatus.FAIL,
                    message="first",
                ),
            ),
        )
    )
    rubric = minimal_rubric(
        effective_rule("SYS-01"),
        effective_rule("STR-01"),
    )
    result = FormalEngine(registry).run(
        execution_context(rubric, bundle=latex_bundle(), latex=latex_project())
    )

    assert [finding.rule_id for finding in result.findings] == ["SYS-01", "STR-01"]


def test_class_script_rule_uses_combined_layer() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "BIB-02",
            frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES}),
            findings=(
                Finding(
                    rule_id="BIB-02",
                    layer=RuleLayer.CLASS_SCRIPT,
                    severity=Severity.ERROR,
                    status=FindingStatus.FAIL,
                    message="bib order",
                ),
            ),
        )
    )
    rubric = minimal_rubric(
        effective_rule(
            "BIB-02",
            layer="class+script",
            capabilities=(Capability.CLASS, Capability.SCRIPT),
        )
    )
    context = execution_context(
        rubric,
        bundle=latex_bundle(),
        latex=latex_project(),
        bib_paths=(Path("refs.bib"),),
    )
    result = FormalEngine(registry).run(context)

    assert result.findings[0].layer is RuleLayer.CLASS_SCRIPT
    assert result.exit_code == 2


def test_script_plus_llm_rule_runs_only_formal_part() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "REV-02",
            frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES}),
            findings=(
                Finding(
                    rule_id="REV-02",
                    layer=RuleLayer.SCRIPT,
                    severity=Severity.WARN,
                    status=FindingStatus.WARN,
                    message="formal heuristic only",
                ),
            ),
        )
    )
    rubric = minimal_rubric(
        effective_rule(
            "REV-02",
            layer="script+llm",
            capabilities=(Capability.SCRIPT, Capability.LLM),
            severity=RubricSeverity.WARN,
        )
    )
    context = execution_context(
        rubric,
        bundle=latex_bundle(),
        latex=latex_project(),
        bib_paths=(Path("refs.bib"),),
    )
    result = FormalEngine(registry).run(context)

    assert len(result.findings) == 1
    assert result.findings[0].layer is RuleLayer.SCRIPT
    assert result.exit_code == 0


def test_dedupe_findings_removes_identical_fingerprints() -> None:
    finding = formal_fail("SYS-01")
    deduped = dedupe_findings((finding, finding))

    assert len(deduped) == 1
    assert finding_fingerprint(deduped[0]) == finding_fingerprint(finding)


def test_rule_timeout_parameter_is_accepted() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "SYS-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            findings=(),
        )
    )
    rubric = minimal_rubric(effective_rule("SYS-01"))
    context = execution_context(rubric, bundle=latex_bundle(), latex=latex_project())
    result = FormalEngine(registry).run(context, rule_timeout_s=30.0)

    assert result.findings == ()


def test_disabled_rule_is_skipped() -> None:
    registry = RuleRegistry()
    registry.register(
        StubFormalRule(
            "SYS-01",
            frozenset({SourceKind.LATEX_PROJECT}),
            findings=(formal_fail("SYS-01"),),
        )
    )
    rubric = minimal_rubric(effective_rule("SYS-01", enabled=False))
    result = FormalEngine(registry).run(
        execution_context(rubric, bundle=latex_bundle(), latex=latex_project())
    )

    assert result.findings == ()
