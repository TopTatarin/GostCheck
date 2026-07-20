import pytest
from pydantic import ValidationError

from normocontrol.domain import Finding, Severity


def test_finding_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Finding(
            rule_id="FMT-01",
            severity=Severity.ERROR,
            message="Нарушены поля",
            unexpected="not allowed",
        )


def test_finding_accepts_unverifiable_without_page() -> None:
    finding = Finding(
        rule_id="PDF-01",
        severity=Severity.UNVERIFIABLE,
        message="Геометрию нельзя определить",
    )

    assert finding.page is None

