"""Bounded retry policy for transient OpenAI-compatible API failures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from time import time

from openai import APIStatusError, APITimeoutError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    stop_before_delay,
    wait_exponential_jitter,
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry bounds; attempts prevent a hot loop while elapsed time is authoritative."""

    max_elapsed: float = 30.0
    max_attempts: int = 4
    initial: float = 0.25
    maximum: float = 5.0


def is_retryable(error: BaseException) -> bool:
    """Retry only timeouts, rate limits, and server-side HTTP failures."""
    if isinstance(error, APITimeoutError):
        return True
    return isinstance(error, APIStatusError) and (
        error.status_code == 429 or 500 <= error.status_code <= 599
    )


def _retry_after_seconds(error: BaseException) -> float | None:
    if not isinstance(error, APIStatusError):
        return None
    value = error.response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time())
        except (TypeError, ValueError, OverflowError):
            return None


def call_with_retry[ResultT](
    operation: Callable[[], ResultT],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] | None = None,
) -> ResultT:
    """Call an operation under bounded exponential jitter and ``Retry-After``."""
    selected = policy or RetryPolicy()
    exponential = wait_exponential_jitter(initial=selected.initial, max=selected.maximum)

    def wait(retry_state: RetryCallState) -> float:
        outcome = retry_state.outcome
        error = outcome.exception() if outcome is not None else None
        retry_after = _retry_after_seconds(error) if error is not None else None
        if retry_after is not None:
            return min(retry_after, selected.max_elapsed)
        return float(exponential(retry_state))

    kwargs: dict[str, object] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    retrying = Retrying(
        retry=retry_if_exception(is_retryable),
        wait=wait,
        stop=stop_after_attempt(selected.max_attempts) | stop_before_delay(selected.max_elapsed),
        reraise=True,
        **kwargs,  # type: ignore[arg-type]
    )
    return retrying(operation)
