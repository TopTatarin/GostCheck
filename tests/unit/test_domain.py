import unicodedata

import pytest
from pydantic import ValidationError

from normocontrol.domain import (
    Evidence,
    ExitCode,
    Finding,
    FindingStatus,
    RuleDefinition,
    RuleLayer,
    RunReport,
    Severity,
    StageResult,
)


def make_finding(**overrides: object) -> Finding:
    values: dict[str, object] = {
        "rule_id": "FMT-01",
        "layer": RuleLayer.SCRIPT,
        "severity": Severity.ERROR,
        "status": FindingStatus.FAIL,
        "message": "Нарушены поля",
    }
    values.update(overrides)
    return Finding.model_validate(values)


def test_run_report_json_round_trip_preserves_unicode_nfd_path() -> None:
    nfd_name = unicodedata.normalize("NFD", "résumé.tex")
    locator = f"каталог с пробелом/{nfd_name}:12"
    finding = make_finding(evidence=(Evidence(locator=locator),), path=locator.split(":")[0])
    report = RunReport(
        tool_version="0.1.0",
        exit_code=ExitCode.FORMAL_FAILURE,
        stages=(StageResult(name="formal", findings=(finding,), duration_ms=12.5),),
    )

    restored = RunReport.model_validate_json(report.model_dump_json())

    assert restored == report
    assert restored.stages[0].findings[0].evidence[0].locator == locator


@pytest.mark.parametrize("layer", [RuleLayer.LLM, RuleLayer.VISION])
def test_advisory_layers_reject_fail_status(layer: RuleLayer) -> None:
    with pytest.raises(ValidationError, match="cannot have status=fail"):
        make_finding(layer=layer)


@pytest.mark.parametrize("status", [FindingStatus.PASS, FindingStatus.SKIPPED])
def test_advisory_layers_allow_only_documented_statuses(status: FindingStatus) -> None:
    with pytest.raises(ValidationError, match="must use an advisory status"):
        make_finding(layer=RuleLayer.LLM, status=status)


@pytest.mark.parametrize(
    "status",
    [
        FindingStatus.WARN,
        FindingStatus.INFO,
        FindingStatus.NOT_APPLICABLE,
        FindingStatus.UNVERIFIABLE,
    ],
)
def test_advisory_layers_accept_non_blocking_statuses(status: FindingStatus) -> None:
    finding = make_finding(layer=RuleLayer.VISION, status=status)

    assert finding.status is status


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            RuleDefinition,
            {"rule_id": "", "description": "Правило", "layer": "script", "severity": "error"},
        ),
        (Evidence, {"description": "страница"}),
        (StageResult, {"name": "formal", "duration_ms": -0.1}),
    ],
)
def test_invalid_contract_values_are_rejected(
    model: type[RuleDefinition] | type[Evidence] | type[StageResult],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_unknown_json_field_is_rejected() -> None:
    payload = make_finding().model_dump()
    payload["unexpected"] = "not allowed"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Finding.model_validate(payload)


def test_minimal_report_json_snapshot_has_no_timestamp() -> None:
    report = RunReport(tool_version="0.1.0")

    assert (
        report.model_dump_json(indent=2)
        == """{
  "schema_version": "1.0",
  "tool_version": "0.1.0",
  "exit_code": 0,
  "stages": []
}"""
    )


def test_unverifiable_finding_does_not_require_page() -> None:
    finding = Finding(
        rule_id="PDF-01",
        layer=RuleLayer.SCRIPT,
        severity=Severity.INFO,
        status=FindingStatus.UNVERIFIABLE,
        message="Геометрию нельзя определить",
    )

    assert finding.status is FindingStatus.UNVERIFIABLE
    assert finding.page is None


def test_report_rejects_exit_code_inconsistent_with_formal_failures() -> None:
    failed_stage = StageResult(name="formal", findings=(make_finding(),))

    with pytest.raises(ValidationError, match="require exit_code=2"):
        RunReport(tool_version="0.1.0", stages=(failed_stage,))
    with pytest.raises(ValidationError, match="requires at least one"):
        RunReport(tool_version="0.1.0", exit_code=ExitCode.FORMAL_FAILURE)


def test_report_accepts_exit_two_for_blocking_formal_unverifiable() -> None:
    incomplete = make_finding(status=FindingStatus.UNVERIFIABLE)
    stage = StageResult(name="formal", findings=(incomplete,))

    report = RunReport(
        tool_version="0.1.0",
        exit_code=ExitCode.FORMAL_FAILURE,
        stages=(stage,),
    )

    assert report.exit_code is ExitCode.FORMAL_FAILURE
    with pytest.raises(ValidationError, match="require exit_code=2"):
        RunReport(tool_version="0.1.0", stages=(stage,))


def test_llm_unverifiable_never_requires_exit_two() -> None:
    advisory = make_finding(
        rule_id="ANN-01",
        layer=RuleLayer.LLM,
        severity=Severity.ERROR,
        status=FindingStatus.UNVERIFIABLE,
    )

    report = RunReport(
        tool_version="0.1.0",
        stages=(StageResult(name="semantic", findings=(advisory,)),),
    )

    assert report.exit_code is ExitCode.SUCCESS
