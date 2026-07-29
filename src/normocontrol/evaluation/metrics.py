"""TP/FP/FN metrics for annotated formal fixtures."""

from __future__ import annotations

from dataclasses import dataclass

from normocontrol.domain import FindingStatus

_TRIGGERED = frozenset({FindingStatus.FAIL, FindingStatus.WARN})


def is_triggered(statuses: tuple[FindingStatus, ...]) -> bool:
    """Return whether a rule produced a visible fail/warn outcome."""
    return any(status in _TRIGGERED for status in statuses)


def expectation_matches(statuses: tuple[FindingStatus, ...], expected: str) -> bool:
    """Check whether observed statuses match the catalog label."""
    if expected == "silent":
        return not is_triggered(statuses)
    if expected == "fail":
        return FindingStatus.FAIL in statuses
    if expected == "warn":
        return FindingStatus.WARN in statuses
    if expected == "detect":
        return is_triggered(statuses)
    msg = f"unsupported expectation: {expected}"
    raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ConfusionCounts:
    """Aggregate confusion matrix counts."""

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float:
        denominator = self.tp + self.fp
        return 0.0 if denominator == 0 else self.tp / denominator

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        return 0.0 if denominator == 0 else self.tp / denominator

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)


@dataclass(frozen=True, slots=True)
class MetricMismatch:
    """One labeled pair where actual outcome differed from expectation."""

    fixture_id: str
    rule_id: str
    expected: str
    actual: tuple[FindingStatus, ...]


@dataclass(frozen=True, slots=True)
class MetricReport:
    """Evaluation summary for one catalog run."""

    counts: ConfusionCounts
    mismatches: tuple[MetricMismatch, ...]
    labeled_pairs: int
    per_rule: tuple[RuleMetric, ...]


@dataclass(frozen=True, slots=True)
class RuleMetric:
    """Confusion matrix and outcome coverage for one formal rule."""

    rule_id: str
    expected: int
    actual: int
    counts: ConfusionCounts
    unverifiable: int
    not_applicable: int
    mismatches: tuple[MetricMismatch, ...]
    labeled_pairs: int


Observation = tuple[str, str, str, tuple[FindingStatus, ...]]


def _compute_counts(observations: tuple[Observation, ...]) -> ConfusionCounts:
    tp = fp = fn = tn = 0
    for _, _, expected, statuses in observations:
        positive = expected in {"fail", "warn", "detect"}
        triggered = is_triggered(statuses)
        if positive and triggered:
            tp += 1
        elif positive and not triggered:
            fn += 1
        elif not positive and triggered:
            fp += 1
        else:
            tn += 1
    return ConfusionCounts(tp=tp, fp=fp, fn=fn, tn=tn)


def compute_metrics(
    observations: tuple[Observation, ...],
    *,
    rule_ids: tuple[str, ...] = (),
) -> MetricReport:
    """Compute TP/FP/FN/TN from fixture/rule observations."""
    mismatches: list[MetricMismatch] = []
    for fixture_id, rule_id, expected, statuses in observations:
        if not expectation_matches(statuses, expected):
            mismatches.append(MetricMismatch(fixture_id, rule_id, expected, statuses))

    ordered_rule_ids = tuple(dict.fromkeys((*rule_ids, *(item[1] for item in observations))))
    per_rule: list[RuleMetric] = []
    for rule_id in ordered_rule_ids:
        selected = tuple(item for item in observations if item[1] == rule_id)
        rule_mismatches = tuple(item for item in mismatches if item.rule_id == rule_id)
        per_rule.append(
            RuleMetric(
                rule_id=rule_id,
                expected=sum(
                    expected in {"fail", "warn", "detect"} for _, _, expected, _ in selected
                ),
                actual=sum(is_triggered(statuses) for _, _, _, statuses in selected),
                counts=_compute_counts(selected),
                unverifiable=sum(
                    status is FindingStatus.UNVERIFIABLE
                    for _, _, _, statuses in selected
                    for status in statuses
                ),
                not_applicable=sum(
                    status is FindingStatus.NOT_APPLICABLE
                    for _, _, _, statuses in selected
                    for status in statuses
                ),
                mismatches=rule_mismatches,
                labeled_pairs=len(selected),
            )
        )
    return MetricReport(
        counts=_compute_counts(observations),
        mismatches=tuple(mismatches),
        labeled_pairs=len(observations),
        per_rule=tuple(per_rule),
    )
