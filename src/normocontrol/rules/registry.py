"""Registry linking rubric rule ids to formal implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from normocontrol.rules.base import FormalRule


class RegistryError(Exception):
    """Raised when registry invariants are violated."""


class DuplicateRuleError(RegistryError):
    """Raised when the same rule id is registered twice."""


class MissingRuleError(RegistryError):
    """Raised when a lookup targets an unknown rule id."""


class ImplementationStatus(StrEnum):
    """Coverage state for one rubric rule id."""

    IMPLEMENTED = "implemented"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class RuleRegistration:
    """One registry entry with explicit coverage metadata."""

    rule_id: str
    status: ImplementationStatus
    implementation: FormalRule | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is ImplementationStatus.IMPLEMENTED and self.implementation is None:
            msg = "implemented registration requires an implementation"
            raise ValueError(msg)
        if self.status is ImplementationStatus.UNSUPPORTED and not self.reason:
            msg = "unsupported registration requires a reason"
            raise ValueError(msg)


class RuleRegistry:
    """In-memory registry with duplicate detection."""

    def __init__(self) -> None:
        self._entries: dict[str, RuleRegistration] = {}

    def register(
        self,
        rule: FormalRule,
        *,
        status: Literal["implemented"] = "implemented",
    ) -> None:
        """Register a concrete rule implementation."""
        if rule.rule_id in self._entries:
            raise DuplicateRuleError(f"duplicate rule id: {rule.rule_id}")
        self._entries[rule.rule_id] = RuleRegistration(
            rule_id=rule.rule_id,
            status=ImplementationStatus.IMPLEMENTED,
            implementation=rule,
        )

    def mark_unsupported(self, rule_id: str, *, reason: str) -> None:
        """Record deliberate lack of implementation for a rubric rule id."""
        if rule_id in self._entries:
            raise DuplicateRuleError(f"duplicate rule id: {rule_id}")
        self._entries[rule_id] = RuleRegistration(
            rule_id=rule_id,
            status=ImplementationStatus.UNSUPPORTED,
            reason=reason,
        )

    def get(self, rule_id: str) -> RuleRegistration | None:
        """Return registration or ``None`` when the id was never declared."""
        return self._entries.get(rule_id)

    def require(self, rule_id: str) -> RuleRegistration:
        """Return registration or raise ``MissingRuleError``."""
        entry = self.get(rule_id)
        if entry is None:
            raise MissingRuleError(f"unknown rule id: {rule_id}")
        return entry

    def rule_ids(self) -> tuple[str, ...]:
        """Return registered ids in sorted order."""
        return tuple(sorted(self._entries))
