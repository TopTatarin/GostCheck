"""Immutable request/state objects for a full normocontrol run."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from normocontrol.domain import ExitCode
from normocontrol.errors import ConfigurationError

STAGE_NAMES = frozenset({"build", "formal", "semantic", "aggregate"})
_RULE_TOKEN = re.compile(r"^[A-Za-z]{3}(?:-\d{2})?$")


class StageName(StrEnum):
    """Fixed pipeline stage order."""

    BUILD = "build"
    FORMAL = "formal"
    SEMANTIC = "semantic"
    AGGREGATE = "aggregate"


STAGE_ORDER: tuple[StageName, ...] = (
    StageName.BUILD,
    StageName.FORMAL,
    StageName.SEMANTIC,
    StageName.AGGREGATE,
)


@dataclass(frozen=True, slots=True)
class OnlyFilter:
    """Resolved ``--only`` selection for stages and/or rule id prefixes."""

    stages: frozenset[StageName] | None = None
    rule_prefixes: tuple[str, ...] = ()

    def includes_stage(self, stage: StageName) -> bool:
        """Return whether ``stage`` should execute."""
        if self.stages is None:
            return True
        return stage in self.stages

    def allows_rule(self, rule_id: str) -> bool:
        """Return whether a rule id matches the optional prefix filter."""
        if not self.rule_prefixes:
            return True
        upper = rule_id.upper()
        return any(
            upper == prefix or upper.startswith(f"{prefix}-") for prefix in self.rule_prefixes
        )


def parse_only(values: tuple[str, ...] | list[str] | None) -> OnlyFilter:
    """Parse ``--only`` tokens into stages and rule prefixes."""
    if not values:
        return OnlyFilter()
    stages: set[StageName] = set()
    prefixes: list[str] = []
    for raw in values:
        token = raw.strip()
        if not token:
            raise ConfigurationError("empty --only value")
        lowered = token.casefold()
        if lowered in STAGE_NAMES:
            stages.add(StageName(lowered))
            continue
        if _RULE_TOKEN.fullmatch(token):
            prefixes.append(token.upper()[:3] if len(token) == 3 else token.upper())
            continue
        raise ConfigurationError(f"unknown --only prefix: {token}")
    return OnlyFilter(
        stages=frozenset(stages) if stages else None,
        rule_prefixes=tuple(dict.fromkeys(prefixes)),
    )


@dataclass(frozen=True, slots=True)
class RunRequest:
    """User-facing inputs for ``normocontrol run``."""

    source: Path
    out_dir: Path
    config_path: Path
    rubric_path: Path
    profile: str | None = None
    no_llm: bool = False
    provider: str | None = None
    only: OnlyFilter = field(default_factory=OnlyFilter)
    apply_final_severity: bool = False
    fail_closed: bool = False
    tool_version: str = "0.1.0"


@dataclass(slots=True)
class RunState:
    """Mutable progress tracker written between stages for resume/diagnostics."""

    completed_stages: list[str] = field(default_factory=list)
    canceled: bool = False
    exit_code: ExitCode = ExitCode.SUCCESS
    messages: list[str] = field(default_factory=list)

    def mark_completed(self, stage: StageName) -> None:
        """Record a finished stage name once."""
        name = stage.value
        if name not in self.completed_stages:
            self.completed_stages.append(name)
