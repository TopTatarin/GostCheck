from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from normocontrol.cli import app
from normocontrol.errors import ConfigValidationError, RubricValidationError
from normocontrol.rubric import (
    Capability,
    ParameterName,
    WorkProfile,
    load_config,
    load_effective_rubric,
    load_rubric,
    normalize_layer,
    profile_mismatch_warning,
)

ROOT = Path(__file__).parents[3]
RUBRIC_PATH = ROOT / "rubric.yaml"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "rubric"


def source_payload() -> dict[str, object]:
    payload = yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def write_yaml(path: Path, payload: object) -> Path:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def config_payload(profile: str = "software") -> dict[str, object]:
    return {
        "version": 1,
        "work_profile": profile,
        "approved_params": [item.value for item in ParameterName],
    }


def test_source_rubric_has_exact_required_distribution_and_unique_ids() -> None:
    rubric = load_rubric(RUBRIC_PATH)

    assert len(rubric.rules) == 64
    assert len({rule.id for rule in rubric.rules}) == 64
    assert Counter(rule.severity.value for rule in rubric.rules) == {
        "error": 26,
        "warn": 34,
        "info": 4,
    }


@pytest.mark.parametrize(
    ("mutation", "path_fragment"),
    [
        (lambda data: data["rules"][0].update(severity="fatal"), "$.rules[0].severity"),
        (
            lambda data: data["rules"][0].update(severity_final="fatal"),
            "$.rules[0].severity_final",
        ),
        (lambda data: data["rules"][0].update(layer="script+quantum"), "$.rules[0].layer"),
        (lambda data: data["rules"][0].pop("check"), "$.rules[0]"),
        (lambda data: data["rules"][0].update(unexpected=True), "$.rules[0]"),
    ],
)
def test_invalid_rule_contract_reports_yaml_path(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], object],
    path_fragment: str,
) -> None:
    payload = source_payload()
    mutation(payload)
    path = write_yaml(tmp_path / "rubric.yaml", payload)

    with pytest.raises(RubricValidationError, match=re.escape(path_fragment)):
        load_rubric(path)


def test_duplicate_rule_id_is_rejected(tmp_path: Path) -> None:
    payload = source_payload()
    payload["rules"][1]["id"] = payload["rules"][0]["id"]  # type: ignore[index]

    with pytest.raises(RubricValidationError, match="duplicate rule id"):
        load_rubric(write_yaml(tmp_path / "rubric.yaml", payload))


@pytest.mark.parametrize("value", ["14", float("nan"), float("inf")])
def test_non_strict_or_non_finite_parameter_is_rejected(tmp_path: Path, value: object) -> None:
    payload = source_payload()
    payload["meta"]["params_to_approve"]["font_size_pt"] = value  # type: ignore[index]

    with pytest.raises(RubricValidationError, match="font_size_pt"):
        load_rubric(write_yaml(tmp_path / "rubric.yaml", payload))


@pytest.mark.parametrize("year", [1999, 2101])
def test_unreasonable_defense_year_is_rejected(tmp_path: Path, year: int) -> None:
    payload = source_payload()
    payload["meta"]["params_to_approve"]["defense_year"] = year  # type: ignore[index]

    with pytest.raises(RubricValidationError, match="defense_year"):
        load_rubric(write_yaml(tmp_path / "rubric.yaml", payload))


def test_only_approved_placeholders_are_expanded(tmp_path: Path) -> None:
    config = config_payload()
    config["approved_params"] = ["font_size_pt"]
    effective = load_effective_rubric(RUBRIC_PATH, write_yaml(tmp_path / "config.yaml", config))
    fmt = next(rule for rule in effective.rules if rule.id == "FMT-01")
    fig = next(rule for rule in effective.rules if rule.id == "FIG-04")

    assert "{font_size_pt}" not in fmt.rule
    assert "{fig_numbering}" in fig.rule
    assert {warning.code for warning in effective.warnings} == {"APPROVAL_REQUIRED"}


def test_unknown_and_unused_placeholders_are_rejected(tmp_path: Path) -> None:
    unknown = source_payload()
    unknown["rules"][0]["rule"] += " {unknown_parameter}"  # type: ignore[index,operator]
    unknown_path = write_yaml(tmp_path / "unknown.yaml", unknown)
    config_path = write_yaml(tmp_path / "config.yaml", config_payload())
    with pytest.raises(RubricValidationError, match="unknown placeholder"):
        load_effective_rubric(unknown_path, config_path)

    unused = source_payload()
    unused["rules"][3]["rule"] = "Основной текст 14 пт"  # type: ignore[index]
    with pytest.raises(RubricValidationError, match="unused parameter"):
        load_effective_rubric(write_yaml(tmp_path / "unused.yaml", unused), config_path)


def test_duplicate_placeholder_expands_and_latex_braces_are_ignored(tmp_path: Path) -> None:
    payload = source_payload()
    payload["rules"][3]["rule"] += " / {font_size_pt}; \\textbf{title}"  # type: ignore[index,operator]
    effective = load_effective_rubric(
        write_yaml(tmp_path / "rubric.yaml", payload),
        write_yaml(tmp_path / "config.yaml", config_payload()),
    )
    text = next(rule.rule for rule in effective.rules if rule.id == "FMT-01")

    assert text.count("14") == 2
    assert r"\textbf{title}" in text


def test_layer_normalization_preserves_source_value() -> None:
    assert normalize_layer("class+script") == (Capability.CLASS, Capability.SCRIPT)
    assert normalize_layer("script+llm") == (Capability.SCRIPT, Capability.LLM)
    with pytest.raises(RubricValidationError, match="quantum"):
        normalize_layer("script+quantum")


def test_llm_profile_suggestion_is_warning_only() -> None:
    warning = profile_mismatch_warning(WorkProfile.SOFTWARE, WorkProfile.RESEARCH)

    assert warning is not None
    assert warning.code == "PROFILE_MISMATCH"
    assert "selected software" in warning.message
    assert profile_mismatch_warning(WorkProfile.SOFTWARE, WorkProfile.SOFTWARE) is None


@pytest.mark.parametrize("profile", ["software", "research"])
def test_effective_profile_matches_golden(tmp_path: Path, profile: str) -> None:
    effective = load_effective_rubric(
        RUBRIC_PATH,
        write_yaml(tmp_path / f"{profile}.yaml", config_payload(profile)),
    )
    actual = {
        "profile": effective.work_profile.value,
        "enabled_count": sum(rule.enabled for rule in effective.rules),
        "disabled_ids": [rule.id for rule in effective.rules if not rule.enabled],
    }
    expected = json.loads((GOLDEN_DIR / f"effective-{profile}.json").read_text(encoding="utf-8"))

    assert actual == expected


@pytest.mark.parametrize("profile", [None, "auto"])
def test_profile_is_required_and_cannot_be_auto(tmp_path: Path, profile: str | None) -> None:
    config: dict[str, object] = {"version": 1}
    if profile is not None:
        config["work_profile"] = profile

    with pytest.raises(ConfigValidationError, match="work_profile"):
        load_config(write_yaml(tmp_path / "config.yaml", config))


def test_config_include_merges_and_detects_cycle(tmp_path: Path) -> None:
    write_yaml(tmp_path / "base.yaml", {"version": 1, "work_profile": "research"})
    child = write_yaml(
        tmp_path / "child.yaml",
        {"include": "base.yaml", "approved_params": ["font_size_pt"]},
    )

    assert load_config(child).work_profile is WorkProfile.RESEARCH

    write_yaml(tmp_path / "a.yaml", {"include": "b.yaml"})
    write_yaml(tmp_path / "b.yaml", {"include": "a.yaml"})
    with pytest.raises(ConfigValidationError, match="cyclic config include"):
        load_config(tmp_path / "a.yaml")


@pytest.mark.parametrize(
    "value",
    [-0.01, 1.01, float("nan"), float("inf"), float("-inf")],
)
def test_geometry_tolerance_rejects_unsafe_values(tmp_path: Path, value: float) -> None:
    config = config_payload()
    config["params"] = {"geometry_tolerance_pt": value}

    with pytest.raises(ConfigValidationError, match="geometry_tolerance_pt"):
        load_config(write_yaml(tmp_path / "config.yaml", config))


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_geometry_tolerance_accepts_finite_bounded_values(
    tmp_path: Path,
    value: float,
) -> None:
    config = config_payload()
    config["params"] = {"geometry_tolerance_pt": value}

    assert (
        load_config(write_yaml(tmp_path / "config.yaml", config)).params.geometry_tolerance_pt
        == value
    )


def test_approved_geometry_tolerance_is_recorded_in_rubric_and_example_config() -> None:
    rubric = load_rubric(RUBRIC_PATH)
    config = load_config(CONFIG_PATH)

    assert rubric.meta.params_to_approve.geometry_tolerance_pt == 0.5
    assert config.params.geometry_tolerance_pt == 0.5
    assert ParameterName.GEOMETRY_TOLERANCE_PT in config.approved_params


def test_bib_03_standards_and_final_severity_overrides_are_preserved() -> None:
    payload = source_payload()
    bib = next(rule for rule in payload["rules"] if rule["id"] == "BIB-03")  # type: ignore[index]

    assert "7.0.5-2008" in bib["rule"]
    assert "7.0.100-2018" in bib["rule"]
    rubric = load_rubric(RUBRIC_PATH)
    overrides = {
        rule.id: rule.severity_final.value
        for rule in rubric.rules
        if rule.severity_final is not None
    }
    assert overrides == {"ANN-03": "error", "REV-01": "error"}

    effective = load_effective_rubric(RUBRIC_PATH, CONFIG_PATH)
    effective_overrides = {
        rule.id: rule.severity_final.value
        for rule in effective.rules
        if rule.severity_final is not None
    }
    assert effective_overrides == overrides


def test_cli_returns_zero_or_three_and_prints_location(tmp_path: Path) -> None:
    runner = CliRunner()
    valid = runner.invoke(
        app,
        ["rubric", "validate", "--rubric", str(RUBRIC_PATH), "--config", str(CONFIG_PATH)],
    )
    payload = source_payload()
    payload["rules"][0].pop("check")  # type: ignore[index]
    invalid_path = write_yaml(tmp_path / "invalid.yaml", payload)
    invalid = runner.invoke(
        app,
        ["rubric", "validate", "--rubric", str(invalid_path), "--config", str(CONFIG_PATH)],
    )

    assert valid.exit_code == 0
    assert "64 rules" in valid.stdout
    assert invalid.exit_code == 3
    assert "$.rules[0]" in invalid.stderr


def test_public_models_reject_unknown_fields() -> None:
    config = load_config(CONFIG_PATH)
    with pytest.raises(ValidationError, match="Extra inputs"):
        type(config).model_validate(config.model_dump() | {"profile": "software"})
