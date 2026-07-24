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
        return 1.0 if denominator == 0 else self.tp / denominator

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        return 1.0 if denominator == 0 else self.tp / denominator

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


def compute_metrics(
    observations: tuple[tuple[str, str, str, tuple[FindingStatus, ...]], ...],
) -> MetricReport:
    """Compute TP/FP/FN/TN from fixture/rule observations."""
    tp = fp = fn = tn = 0
    mismatches: list[MetricMismatch] = []
    for fixture_id, rule_id, expected, statuses in observations:
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
        if not expectation_matches(statuses, expected):
            mismatches.append(MetricMismatch(fixture_id, rule_id, expected, statuses))
    return MetricReport(
        counts=ConfusionCounts(tp=tp, fp=fp, fn=fn, tn=tn),
        mismatches=tuple(mismatches),
        labeled_pairs=len(observations),
    )
