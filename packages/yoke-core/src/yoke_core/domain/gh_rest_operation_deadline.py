"""Operation-wide deadline accounting for retried GitHub REST calls."""

from __future__ import annotations

import math
from collections.abc import Callable


class GitHubRestOperationDeadlineError(TimeoutError):
    """A GitHub REST request exhausted its whole-operation deadline."""


def require_remaining(deadline: float, *, clock: Callable[[], float]) -> float:
    """Return positive operation time remaining or raise a typed timeout."""

    remaining = deadline - clock()
    if not math.isfinite(remaining) or remaining <= 0:
        raise GitHubRestOperationDeadlineError(
            "GitHub REST operation exceeded the time limit"
        )
    return remaining


def wait_before_retry(
    deadline: float,
    wait_seconds: float,
    *,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> None:
    """Sleep only when the complete backoff fits inside the operation."""

    remaining = require_remaining(deadline, clock=clock)
    try:
        wait = float(wait_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GitHubRestOperationDeadlineError(
            "GitHub REST retry delay is invalid"
        ) from exc
    if not math.isfinite(wait) or wait < 0:
        raise GitHubRestOperationDeadlineError("GitHub REST retry delay is invalid")
    if wait >= remaining:
        raise GitHubRestOperationDeadlineError(
            "GitHub REST operation exceeded the time limit"
        )
    sleeper(wait)
    require_remaining(deadline, clock=clock)


__all__ = [
    "GitHubRestOperationDeadlineError",
    "require_remaining",
    "wait_before_retry",
]
