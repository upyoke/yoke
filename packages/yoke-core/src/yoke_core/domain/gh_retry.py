"""GitHub transient-failure classifier shared by REST callers.

The classifier surface (:data:`RETRY_STDERR_MATCHERS`,
:func:`is_retryable_text`, :data:`MAX_RETRIES`, :data:`BACKOFF_SECONDS`)
is the canonical list of GitHub-API transient-failure signatures:
rate-limit / 500 / 502 / 503 / Bad Gateway / Service Unavailable
transport noise, "Could not resolve to a {Node}" GraphQL propagation
races on fresh resources, and the ``mergePullRequest`` "Base branch was
modified" cache-staleness race. The REST transport in
:mod:`yoke_core.domain.gh_rest_transport` consumes this matcher list,
so adding a transient class (or removing one) only requires editing
the table here.

The legacy subprocess runner (``run_command``) has been retired —
callers route their requests through
:func:`yoke_core.domain.gh_rest_transport.request_with_retry` and
inherit the same retry policy via the constants below.
"""

from __future__ import annotations

from typing import Tuple


MAX_RETRIES = 3
BACKOFF_SECONDS = (5, 15, 45)


# Canonical transient-failure classifier. Each entry is
# ``(needle, case_sensitive)``. A response is retryable when any needle is
# present in the response body / stderr text; case-insensitive matches lower
# the haystack before checking, case-sensitive matches scan the raw text.
RETRY_STDERR_MATCHERS: Tuple[Tuple[str, bool], ...] = (
    ("rate limit", False),
    ("500", True),
    ("502", True),
    ("503", True),
    ("Bad Gateway", True),
    ("Service Unavailable", True),
    # GitHub GraphQL returns "Could not resolve to a <Node>" for a
    # just-created resource while its backend finishes propagating. The
    # underlying resource already exists; a retry a few seconds later
    # succeeds.
    ("could not resolve to a", False),
    # GitHub's mergePullRequest mutation surfaces "Base branch was
    # modified. Review and try the merge again." when its GraphQL cache has
    # not yet caught up with the just-landed CI-status update on the head
    # branch. The base has not actually moved; a second attempt succeeds.
    # Callers can pair this matcher with a pre-retry hook that re-validates
    # mergeability before the shared backoff sleeps and retries.
    ("base branch was modified", False),
)


def is_retryable_text(text: str) -> bool:
    """Return True when ``text`` contains any canonical transient signature.

    Shared by the REST transport so the retry-eligibility decision lives
    in exactly one place.
    """
    if not text:
        return False
    lowered = text.lower()
    for needle, case_sensitive in RETRY_STDERR_MATCHERS:
        haystack = text if case_sensitive else lowered
        probe = needle if case_sensitive else needle.lower()
        if probe in haystack:
            return True
    return False


def _retryable(stderr: str) -> bool:
    """Backwards-compatible alias for :func:`is_retryable_text`."""
    return is_retryable_text(stderr)
