from __future__ import annotations

import json
from pathlib import Path

import pytest

from normocontrol.rubric.expansion import expand_rubric, normalize_layer
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rubric.models import Capability, WorkProfile
from normocontrol.semantic.engine import RULE_SPECS
from normocontrol.semantic.schemas import IMPLEMENTED_RULE_IDS, SEMANTIC_RULE_IDS

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("profile", "snapshot_name"),
    (
        (WorkProfile.SOFTWARE, "effective-software.json"),
        (WorkProfile.RESEARCH, "effective-research.json"),
    ),
)
def test_semantic_registry_matches_rubric_and_effective_profiles(
    profile: WorkProfile,
    snapshot_name: str,
) -> None:
    rubric = load_rubric(ROOT / "rubric.yaml")
    rubric_semantic = {
        rule.id for rule in rubric.rules if Capability.LLM in normalize_layer(rule.layer)
    }
    assert rubric_semantic == SEMANTIC_RULE_IDS

    config = load_config(ROOT / "normocontrol.yaml.example").model_copy(
        update={"work_profile": profile}
    )
    effective = expand_rubric(rubric, config)
    effective_semantic = {
        rule.id for rule in effective.rules if Capability.LLM in rule.capabilities
    }
    assert effective_semantic == SEMANTIC_RULE_IDS

    snapshot = json.loads(
        (ROOT / "tests" / "fixtures" / "rubric" / snapshot_name).read_text(encoding="utf-8")
    )
    disabled = {rule.id for rule in effective.rules if not rule.enabled}
    assert effective.work_profile.value == snapshot["profile"]
    assert len(effective.rules) - len(disabled) == snapshot["enabled_count"]
    assert disabled == set(snapshot["disabled_ids"])
    assert {rule.id for rule in effective.rules if rule.enabled} >= (
        IMPLEMENTED_RULE_IDS - disabled
    )


def test_implemented_ids_have_exactly_one_strict_rule_spec() -> None:
    assert set(RULE_SPECS) == IMPLEMENTED_RULE_IDS
    assert IMPLEMENTED_RULE_IDS == SEMANTIC_RULE_IDS
    for rule_id, spec in RULE_SPECS.items():
        assert spec.rule_id == rule_id
        assert spec.section_roles
        assert spec.requirement
        assert spec.elements
        assert len(spec.elements) == len(set(spec.elements))
