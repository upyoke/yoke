"""HTTP response classification for the GitHub REST transport."""

from __future__ import annotations

from collections.abc import Mapping

from yoke_core.domain.gh_rest_transport_errors import (
    RateLimitedError,
    RestAuthError,
    RestNotFoundError,
    RestServerError,
    RestTransportError,
    RestUnprocessableError,
)


_RATE_LIMIT_BODY_MARKERS = (
    "API rate limit exceeded",
    "secondary rate limit",
    "abuse detection mechanism",
)


def is_rate_limit_body(body_text: str) -> bool:
    """Return whether GitHub's 403 body identifies a rate limit."""
    return bool(body_text) and any(
        marker in body_text for marker in _RATE_LIMIT_BODY_MARKERS
    )


def classify_http_error(
    status: int,
    body_text: str,
    headers: Mapping[str, str],
) -> RestTransportError:
    """Map one GitHub HTTP failure to its public typed error."""
    del headers
    snippet = body_text.strip()[:240]
    body_arg: dict = {"status": status, "body": body_text}
    if status == 429 or (status == 403 and is_rate_limit_body(body_text)):
        return RateLimitedError(f"HTTP {status} rate limit: {snippet}", **body_arg)
    if status in (401, 403):
        return RestAuthError(f"HTTP {status}: {snippet}", **body_arg)
    if status == 404:
        return RestNotFoundError(f"HTTP {status}: {snippet}", **body_arg)
    if status == 422:
        return RestUnprocessableError(f"HTTP {status}: {snippet}", **body_arg)
    if 500 <= status < 600:
        return RestServerError(f"HTTP {status}: {snippet}", **body_arg)
    return RestTransportError(f"HTTP {status}: {snippet}", **body_arg)


__all__ = ["classify_http_error", "is_rate_limit_body"]
