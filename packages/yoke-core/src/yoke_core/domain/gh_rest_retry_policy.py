"""Replay-safety policy for GitHub REST retries."""

from __future__ import annotations

from yoke_core.domain import gh_retry
from yoke_core.domain.gh_rest_transport_errors import (
    RateLimitedError,
    RestNetworkError,
    RestTransportError,
    RestUnprocessableError,
)


_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
_METHOD_REPLAY_SAFE = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


def request_replay_is_safe(*, method: str, replay_safe: bool | None) -> bool:
    """Return whether an ambiguous failure may replay this operation."""
    if replay_safe is not None:
        return replay_safe
    return str(method or "").upper() in _METHOD_REPLAY_SAFE


def is_retryable_error(exc: RestTransportError) -> bool:
    """Return whether one typed failure is transient when replay is safe."""
    if isinstance(exc, (RestNetworkError, RateLimitedError)):
        return True
    if isinstance(exc, RestUnprocessableError):
        text = (exc.body or "") + " " + (str(exc) or "")
        return gh_retry.is_retryable_text(text)
    if exc.status is None:
        return False
    return exc.status in _RETRYABLE_HTTP_STATUSES


__all__ = ["is_retryable_error", "request_replay_is_safe"]
