"""Shared recognition of GitHub HTTP rate-limit bodies.

GitHub answers quota exhaustion as HTTP 429 *or* as HTTP 403 whose body
names a rate limit / abuse window. The client token refresh path and the
engine REST transport both need that body test, and the client package
cannot import the engine, so the markers live here.
"""

from __future__ import annotations

RATE_LIMIT_BODY_MARKERS = (
    "API rate limit exceeded",
    "secondary rate limit",
    "abuse detection mechanism",
)


def is_rate_limit_body(body_text: str) -> bool:
    """Return whether GitHub's response body identifies a rate limit."""
    return bool(body_text) and any(
        marker in body_text for marker in RATE_LIMIT_BODY_MARKERS
    )


__all__ = ["RATE_LIMIT_BODY_MARKERS", "is_rate_limit_body"]
