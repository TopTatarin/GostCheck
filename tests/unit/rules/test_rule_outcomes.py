"""Unit tests fixing the class_ok/script_ok truth table of combine_class_script()."""

from __future__ import annotations

import pytest

from normocontrol.domain import FindingStatus
from normocontrol.rules._rule_outcomes import combine_class_script

from .helpers import effective_rule

_MESSAGES: dict[str, str] = {
    "pass_message": "pass",
    "class_fail_message": "class-fail",
    "script_fail_message": "script-fail",
    "class_missing_message": "class-missing",
    "script_missing_message": "script-missing",
}


@pytest.mark.parametrize(
    ("class_ok", "script_ok", "expected_status", "expected_message"),
    [
        (True, True, FindingStatus.PASS, "pass"),
        (False, True, FindingStatus.FAIL, "class-fail"),
        (None, True, FindingStatus.UNVERIFIABLE, "class-missing"),
        (True, False, FindingStatus.FAIL, "script-fail"),
        (None, False, FindingStatus.FAIL, "script-fail"),
        (True, None, FindingStatus.UNVERIFIABLE, "script-missing"),
        (False, None, FindingStatus.FAIL, "class-fail"),
        (None, None, FindingStatus.UNVERIFIABLE, "class-missing"),
    ],
)
def test_combine_class_script_truth_table(
    class_ok: bool | None,
    script_ok: bool | None,
    expected_status: FindingStatus,
    expected_message: str,
) -> None:
    outcome = combine_class_script(
        effective_rule("BIB-02", layer="class+script"),
        class_ok=class_ok,
        script_ok=script_ok,
        **_MESSAGES,
    )
    finding = outcome.findings[0]
    assert finding.status is expected_status
    assert finding.message == expected_message


@pytest.mark.parametrize(
    ("class_ok", "script_ok", "expected_status", "expected_message"),
    [
        (True, False, FindingStatus.WARN, "script-fail"),
        (None, False, FindingStatus.WARN, "script-fail"),
        (False, True, FindingStatus.FAIL, "class-fail"),
    ],
)
def test_combine_class_script_script_warn_flag(
    class_ok: bool | None,
    script_ok: bool | None,
    expected_status: FindingStatus,
    expected_message: str,
) -> None:
    outcome = combine_class_script(
        effective_rule("TAB-02", layer="class+script"),
        class_ok=class_ok,
        script_ok=script_ok,
        script_warn=True,
        **_MESSAGES,
    )
    finding = outcome.findings[0]
    assert finding.status is expected_status
    assert finding.message == expected_message


def test_combine_class_script_optional_true_class_none_script_passes() -> None:
    """Documented script_optional exception: class_ok=True, script_ok=None -> PASS."""
    outcome = combine_class_script(
        effective_rule("BIB-03", layer="class+script"),
        class_ok=True,
        script_ok=None,
        script_optional=True,
        **_MESSAGES,
    )
    finding = outcome.findings[0]
    assert finding.status is FindingStatus.PASS
    assert finding.message == "pass"


def test_combine_class_script_repeated_call_is_deterministic() -> None:
    kwargs = {"class_ok": None, "script_ok": True, **_MESSAGES}
    first = combine_class_script(effective_rule("BIB-02", layer="class+script"), **kwargs)
    second = combine_class_script(effective_rule("BIB-02", layer="class+script"), **kwargs)
    assert first.findings == second.findings
