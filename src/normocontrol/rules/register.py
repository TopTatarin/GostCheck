"""Register formal rule implementations."""

from __future__ import annotations

from normocontrol.rules.algorithm import algorithm_rules
from normocontrol.rules.annotation import annotation_rules
from normocontrol.rules.appendix import appendix_rules
from normocontrol.rules.bibliography import bibliography_rules
from normocontrol.rules.captions import caption_rules
from normocontrol.rules.figures import figures_rules
from normocontrol.rules.formatting import formatting_rules
from normocontrol.rules.formulas import formula_rules
from normocontrol.rules.monolith import monolith_rules
from normocontrol.rules.registry import RuleRegistry
from normocontrol.rules.review import review_rules
from normocontrol.rules.section_floats import section_float_rules
from normocontrol.rules.structure import structure_rules
from normocontrol.rules.system import system_rules
from normocontrol.rules.tables import tables_rules
from normocontrol.tools.chktex import ChktexRunner
from normocontrol.tools.latexmk import LatexBuildService


def register_d02_rules(
    registry: RuleRegistry,
    *,
    build_service: LatexBuildService | None = None,
    chktex: ChktexRunner | None = None,
) -> RuleRegistry:
    """Register SYS/STR/ANN/INT formal rules."""
    rules = (
        *system_rules(build_service=build_service, chktex=chktex),
        *structure_rules(),
        *monolith_rules(),
        *annotation_rules(),
        *appendix_rules(),
        *algorithm_rules(),
        *section_float_rules(),
    )
    for rule in rules:
        registry.register(rule)
    return registry


def register_d03_rules(registry: RuleRegistry) -> RuleRegistry:
    """Register FMT formatting rules."""
    for rule in formatting_rules():
        registry.register(rule)
    return registry


def register_d04_rules(registry: RuleRegistry) -> RuleRegistry:
    """Register FIG/TAB/CAP/MTH float and formula rules."""
    rules = (
        *figures_rules(),
        *tables_rules(),
        *caption_rules(),
        *formula_rules(),
    )
    for rule in rules:
        registry.register(rule)
    return registry


def register_d05_rules(registry: RuleRegistry) -> RuleRegistry:
    """Register BIB/REV bibliography and review rules."""
    rules = (
        *bibliography_rules(),
        *review_rules(),
    )
    for rule in rules:
        registry.register(rule)
    return registry


def default_formal_registry(
    *,
    build_service: LatexBuildService | None = None,
    chktex: ChktexRunner | None = None,
) -> RuleRegistry:
    """Create a registry with all implemented formal rules."""
    registry = RuleRegistry()
    register_d02_rules(registry, build_service=build_service, chktex=chktex)
    register_d03_rules(registry)
    register_d04_rules(registry)
    register_d05_rules(registry)
    return registry
