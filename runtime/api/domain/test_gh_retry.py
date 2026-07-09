"""Classifier-surface tests for :mod:`yoke_core.domain.gh_retry`.

The subprocess runner has been retired; the classifier (matchers,
``is_retryable_text``, ``MAX_RETRIES``, ``BACKOFF_SECONDS``) remains
imported by the REST transport. These tests pin the public surface.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import gh_retry


def test_classifier_constants_importable():
    """The REST transport pulls these four names directly."""
    assert isinstance(gh_retry.MAX_RETRIES, int) and gh_retry.MAX_RETRIES >= 1
    assert isinstance(gh_retry.BACKOFF_SECONDS, tuple) and len(gh_retry.BACKOFF_SECONDS) >= 1
    assert isinstance(gh_retry.RETRY_STDERR_MATCHERS, tuple)
    assert callable(gh_retry.is_retryable_text)


@pytest.mark.parametrize(
    "stderr_text",
    [
        "rate limit exceeded",
        "HTTP 500: Failed to run workflow dispatch",
        "502 Bad Gateway",
        "503 Service Unavailable",
        "Bad Gateway",
        "Service Unavailable",
        "GraphQL: Could not resolve to a PullRequest with the number of 3309",
        "GraphQL: Could not resolve to a Node with the global id of X",
        "GraphQL: Base branch was modified. Review and try the merge again.",
    ],
)
def test_is_retryable_text_matches_canonical_transient_signatures(stderr_text):
    assert gh_retry.is_retryable_text(stderr_text) is True


@pytest.mark.parametrize(
    "stderr_text",
    [
        "permission denied",
        "not found",
        "",
        "fatal: repository does not exist",
    ],
)
def test_is_retryable_text_rejects_terminal_failures(stderr_text):
    assert gh_retry.is_retryable_text(stderr_text) is False


def test_retryable_alias_preserved_for_legacy_callers():
    """The lowercase ``_retryable`` alias is the legacy shape kept for
    backwards-compatible imports. It MUST delegate to ``is_retryable_text``."""
    assert gh_retry._retryable("rate limit hit") is True
    assert gh_retry._retryable("permission denied") is False


def test_subprocess_runner_retired():
    """``run_command`` is the retired subprocess runner. The classifier
    module no longer exports it; callers route through
    :func:`gh_rest_transport.request_with_retry`."""
    assert not hasattr(gh_retry, "run_command")


def test_rest_transport_imports_classifier():
    """Defense-in-depth: the REST transport binds the classifier names
    we expose. A rename in this module would break the transport's
    retry decision."""
    from yoke_core.domain import gh_rest_transport

    assert gh_rest_transport.gh_retry is gh_retry
    assert gh_rest_transport.gh_retry.MAX_RETRIES == gh_retry.MAX_RETRIES
    assert (
        gh_rest_transport.gh_retry.BACKOFF_SECONDS
        == gh_retry.BACKOFF_SECONDS
    )
