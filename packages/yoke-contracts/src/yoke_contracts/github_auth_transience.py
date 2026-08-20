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

from typing import Iterator


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


__all__ = [
    "GITHUB_AUTH_READ_ATTEMPTS",
    "GITHUB_AUTH_READ_BACKOFF_SECONDS",
    "GITHUB_AUTH_RETRY_RECIPE",
    "GITHUB_AUTH_STATUS_CHECK_RECIPE",
    "TransientGitHubAuthError",
    "auth_failure_chain",
    "is_transient_auth_failure",
    "retry_backoff_seconds",
]
