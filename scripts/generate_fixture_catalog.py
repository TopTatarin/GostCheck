"""Generate annotated formal fixture catalog for D-06 metrics."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests" / "fixtures" / "formal" / "catalog.yaml"

D02_RULES = (
    "SYS-01",
    "SYS-02",
    "SYS-03",
    "STR-01",
    "STR-02",
    "STR-03",
    "STR-04",
    "ANN-02",
    "INT-02",
)
FMT_RULES = ("FMT-01", "FMT-02", "FMT-03", "FMT-04", "FMT-05")
D04_RULES = (
    "FIG-01",
    "FIG-02",
    "FIG-03",
    "FIG-04",
    "FIG-05",
    "FIG-06",
    "FIG-07",
    "TAB-01",
    "TAB-02",
    "TAB-03",
    "CAP-01",
    "MTH-01",
)
D05_RULES = (
    "BIB-01",
    "BIB-02",
    "BIB-03",
    "BIB-04",
    "BIB-05",
    "REV-01",
    "REV-02",
    "REV-03",
    "REV-04",
    "REV-07",
)


def _silent(rule_ids: tuple[str, ...]) -> dict[str, str]:
    return {rule_id: "silent" for rule_id in rule_ids}


def _entry(
    fixture_id: str,
    *,
    latex: str | None = None,
    pdf: str | None = None,
    bib_paths: tuple[str, ...] = (),
    labels: dict[str, str],
) -> dict[str, object]:
    payload: dict[str, object] = {"id": fixture_id, "labels": labels}
    if latex is not None:
        payload["latex"] = latex
    if pdf is not None:
        payload["pdf"] = pdf
    if bib_paths:
        payload["bib_paths"] = list(bib_paths)
    return payload


def _fail_entry(
    fixture_id: str,
    path: str,
    rule_id: str,
    *,
    outcome: str,
    bib_paths: tuple[str, ...] = (),
    extra_labels: dict[str, str] | None = None,
) -> dict[str, object]:
    labels = {rule_id: outcome}
    if extra_labels:
        labels.update(extra_labels)
    return _entry(
        fixture_id,
        latex=path,
        bib_paths=bib_paths,
        labels=labels,
    )


def build_catalog() -> dict[str, object]:
    fixtures: list[dict[str, object]] = []

    fixtures.append(
        _entry("d02-pass", latex="tests/fixtures/latex/pass", labels=_silent(D02_RULES))
    )
    for name, folder, rule_id in (
        ("d02-fail-sys01", "fail_sys01", "SYS-01"),
        ("d02-fail-sys02", "fail_sys02", "SYS-02"),
        ("d02-fail-str01", "fail_str01", "STR-01"),
        ("d02-fail-str02", "fail_str02", "STR-02"),
        ("d02-fail-ann02", "fail_ann02", "ANN-02"),
        ("d02-fail-int02", "fail_int02", "INT-02"),
    ):
        fixtures.append(
            _fail_entry(
                name,
                f"tests/fixtures/latex/{folder}",
                rule_id,
                outcome="fail",
            )
        )

    fixtures.append(
        _entry(
            "d03-pdf-pass",
            latex="tests/fixtures/latex/pass",
            pdf="tests/fixtures/pdf/fmt_pass.pdf",
            labels=_silent(FMT_RULES),
        )
    )
    for name, rule_id, pdf_name in (
        ("d03-pdf-wrong-font", "FMT-01", "fmt_wrong_font.pdf"),
        ("d03-pdf-non-bold-heading", "FMT-02", "fmt_non_bold_heading.pdf"),
        ("d03-pdf-margin-overflow", "FMT-05", "fmt_margin_overflow.pdf"),
    ):
        fixtures.append(
            _entry(
                name,
                latex="tests/fixtures/latex/pass",
                pdf=f"tests/fixtures/pdf/{pdf_name}",
                labels={rule_id: "fail"},
            )
        )

    fixtures.append(
        _entry(
            "d04-floats-pass",
            latex="tests/fixtures/latex/floats/pass",
            labels=_silent(D04_RULES),
        )
    )
    for name, folder, rule_id in (
        ("d04-fail-fig02", "fail_fig02", "FIG-02"),
        ("d04-fail-fig03", "fail_fig03", "FIG-03"),
        ("d04-fail-cap01", "fail_cap01", "CAP-01"),
        ("d04-fail-mth01", "fail_mth01", "MTH-01"),
    ):
        fixtures.append(
            _fail_entry(
                name,
                f"tests/fixtures/latex/floats/{folder}",
                rule_id,
                outcome="fail",
                extra_labels={"FIG-02": "fail"} if rule_id == "FIG-03" else None,
            )
        )
    fixtures.append(
        _entry(
            "d04-fig01-pass",
            latex="tests/fixtures/latex/floats/pass",
            pdf="tests/fixtures/pdf/fig01_pass.pdf",
            labels={**_silent(D04_RULES), "FIG-01": "silent"},
        )
    )
    fixtures.append(
        _entry(
            "d04-fig01-warn",
            latex="tests/fixtures/latex/floats/pass",
            pdf="tests/fixtures/pdf/fig01_warn.pdf",
            labels={**_silent(D04_RULES), "FIG-01": "warn"},
        )
    )

    fixtures.append(
        _entry(
            "d05-bib-pass",
            latex="tests/fixtures/latex/bib/pass",
            bib_paths=("tests/fixtures/latex/bib/pass/refs.bib",),
            labels=_silent(D05_RULES),
        )
    )
    for name, rule_id, outcome in (
        ("fail_bib01", "BIB-01", "fail"),
        ("fail_bib02", "BIB-02", "fail"),
        ("fail_bib03", "BIB-03", "fail"),
        ("fail_bib04", "BIB-04", "fail"),
        ("fail_bib05", "BIB-05", "warn"),
        ("fail_rev01", "REV-01", "warn"),
        ("fail_rev02", "REV-02", "warn"),
        ("fail_rev03", "REV-03", "warn"),
        ("fail_rev04", "REV-04", "fail"),
        ("fail_rev07", "REV-07", "warn"),
    ):
        fixtures.append(
            _fail_entry(
                f"d05-{name.replace('_', '-')}",
                f"tests/fixtures/latex/bib/{name}",
                rule_id,
                outcome=outcome,
                bib_paths=(f"tests/fixtures/latex/bib/{name}/refs.bib",),
            )
        )

    return {"version": 1, "fixtures": fixtures}


def main() -> None:
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    payload = build_catalog()
    CATALOG.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    print(f"catalog={CATALOG}")
    print(f"fixtures={len(payload['fixtures'])}")


if __name__ == "__main__":
    main()
