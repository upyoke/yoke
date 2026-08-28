"""Shared marker and retry budget for transient GitHub authorization reads.

A machine-local GitHub App user-authorization read fails for two very different
reasons. Either the stored authorization is absent or invalid, which only a
reconnect repairs, or the read collided with another local process, a slow
network, or a single unauthorized response, which a retry repairs. The engine
resolver and the client-side token providers live in different packages, so the
marker exception, the chain walk that finds it, and the retry budget all live
here where both sides can read them.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")


class TransientGitHubAuthError(Exception):
    """A GitHub authorization read failed in a way a retry can resolve."""


GITHUB_AUTH_READ_ATTEMPTS = 3
GITHUB_AUTH_READ_BACKOFF_SECONDS = (0.5, 2.0)
GITHUB_AUTH_RETRY_RECIPE = (
    "retry the command, and run `yoke github status` if it keeps failing"
)
GITHUB_AUTH_STATUS_CHECK_RECIPE = (
    "run `yoke github status`, and reconnect GitHub on this machine only if "
    "it reports the authorization missing"
)

_CAUSE_CHAIN_LIMIT = 16


def auth_failure_chain(error: BaseException | None) -> Iterator[BaseException]:
    """Yield an error and its explicitly raised-from causes, outermost first.

    Only ``__cause__`` is followed. Implicit ``__context__`` links attach
    exceptions that were merely in flight during handling, which would classify
    an already-handled transient failure as the cause of a permanent one.
    """

    current = error
    for _ in range(_CAUSE_CHAIN_LIMIT):
        if current is None:
            return
        yield current
        current = current.__cause__


def is_transient_auth_failure(error: BaseException | None) -> bool:
    """Report whether a raised authorization failure is retry-shaped."""

    return any(
        isinstance(cause, TransientGitHubAuthError)
        for cause in auth_failure_chain(error)
    )


def retry_backoff_seconds(attempt: int) -> float:
    """Return the wait before the attempt following a zero-based attempt."""

    backoff = GITHUB_AUTH_READ_BACKOFF_SECONDS
    if not backoff:
        return 0.0
    return backoff[min(max(attempt, 0), len(backoff) - 1)]


def call_with_transient_retry(
    call: Callable[[], T],
    *,
    is_transient: Callable[[BaseException], bool] = is_transient_auth_failure,
    sleep: Callable[[float], Any] | None = None,
    attempts: int = GITHUB_AUTH_READ_ATTEMPTS,
) -> T:
    """Replay *call* while it raises a retry-shaped authorization failure.

    Contention is the expected failure on a busy machine, and the budget here
    is what keeps one caller's collision from surfacing as a refusal the
    operator has to act on. A permanent failure raises on the first attempt,
    and the last attempt's exception is the one that reaches the caller, so
    the diagnosis is never replaced by the retry machinery.
    """

    for attempt in range(attempts):
        try:
            return call()
        except BaseException as exc:  # noqa: BLE001 - classified, then re-raised
            if attempt + 1 >= attempts or not is_transient(exc):
                raise
            (sleep or time.sleep)(retry_backoff_seconds(attempt))
    raise AssertionError("retry budget must be at least one attempt")


__all__ = [
    "call_with_transient_retry",
    "GITHUB_AUTH_READ_ATTEMPTS",
    "GITHUB_AUTH_READ_BACKOFF_SECONDS",
    "GITHUB_AUTH_RETRY_RECIPE",
    "GITHUB_AUTH_STATUS_CHECK_RECIPE",
    "TransientGitHubAuthError",
    "auth_failure_chain",
    "is_transient_auth_failure",
    "retry_backoff_seconds",
]
