"""What a provider failure tells the person who has to clear it.

One summary code cannot separate a rate limit from a revoked permission from
a 502, yet those need three different actions and only two of them are worth
retrying. The stable reason code stays the code; these pin that the
classification and status reach the recovery text an operator actually reads.
"""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSourceUnavailable,
)


BASE = "a" * 40
TIP = "c" * 40


class _Recorder:
    """Stand in for the REST transport and raise what the test supplies."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.paths: list[str] = []

    def __call__(self, request: Any, *, token: str) -> Any:
        del token
        self.paths.append(request.path)
        answer = self._responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return type("Response", (), {"status": 200, "headers": {}, "body": answer})()


def _source(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> Any:
    monkeypatch.setattr(provider, "request_with_retry", _Recorder(responses))
    return provider.RepositoryProviderSource("owner/repo", "token")


def test_a_server_failure_reads_as_transient(monkeypatch: pytest.MonkeyPatch):
    from yoke_core.domain.gh_rest_transport_errors import RestServerError

    source = _source(
        monkeypatch,
        [RestServerError("502 bad gateway", status=502)],
    )

    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        source.commit_range(BASE, TIP)

    assert "rest_server_error" in raised.value.recovery
    assert "HTTP 502" in raised.value.recovery
    assert "transient" in raised.value.recovery


def test_a_permission_failure_does_not_prescribe_a_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    """Retrying a revoked permission returns the same answer forever."""
    from yoke_core.domain.gh_rest_transport_errors import RestAuthError

    source = _source(
        monkeypatch,
        [RestAuthError("403 forbidden", status=403)],
    )

    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        source.commit_range(BASE, TIP)

    assert raised.value.reason == "repository_provider_read_failed"
    assert "not authorized to read repository contents" in raised.value.recovery
    assert "Retrying will not change that" in raised.value.recovery


def test_an_unpublished_head_is_named_rather_than_called_a_read_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    """A 404 is the provider answering, not the provider failing.

    The lane head was recorded locally and never pushed. Reporting that as
    "the repository read failed" sends an owner to inspect a binding that is
    working perfectly, and no amount of retrying publishes the commit.
    """
    from yoke_core.domain.gh_rest_transport_errors import RestNotFoundError
    from yoke_core.domain.repository_provider_refusal import HEAD_UNPUBLISHED

    source = _source(
        monkeypatch,
        [RestNotFoundError("404 not found", status=404)],
    )

    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        source.commit_range(BASE, TIP)

    assert raised.value.reason == HEAD_UNPUBLISHED
    assert TIP in raised.value.recovery
    assert "never published to this remote" in raised.value.recovery
    assert "Publish or land the lane" in raised.value.recovery


def test_a_rate_limit_says_so_rather_than_blaming_the_binding(
    monkeypatch: pytest.MonkeyPatch,
):
    from yoke_core.domain.gh_rest_transport_errors import RateLimitedError

    source = _source(
        monkeypatch,
        [RateLimitedError("secondary rate limit", status=403)],
    )

    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        source.commit_range(BASE, TIP)

    assert "rate limit" in raised.value.recovery
    assert "nothing about the project's binding needs changing" in (
        raised.value.recovery
    )
