"""Absolute-deadline coverage for GitHub response-body transports."""

from __future__ import annotations

import urllib.error

import pytest

from yoke_contracts.github_origin import validate_github_api_endpoint
from yoke_core.domain import gh_rest_transport
from yoke_core.domain import github_actions_logs
from yoke_core.domain import github_app_installation_token_transport
from yoke_core.domain import github_response_safety
from yoke_core.domain.github_app_token_models import GitHubAppTokenError
from yoke_core.domain.github_app_verification_response import (
    GitHubAppVerificationResponseError,
    read_bounded_verification_response,
)


class _MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _SlowTrickleResponse:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, clock: _MutableClock, *, advance: float = 0.6) -> None:
        self.clock = clock
        self.advance = advance
        self.read_calls = 0
        self.socket_timeouts: list[float] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self) -> None:
        return None

    def geturl(self) -> str:
        return "https://api.github.com/slow"

    def read(self, _size: int = -1) -> bytes:
        raise AssertionError("network responses must use incremental reads")

    def read1(self, _size: int = -1) -> bytes:
        self.read_calls += 1
        self.clock.advance(self.advance)
        return b"{" if self.read_calls == 1 else b"}"

    def settimeout(self, seconds: float) -> None:
        self.socket_timeouts.append(seconds)


def _bind_clock(monkeypatch, clock: _MutableClock) -> None:
    monkeypatch.setattr(github_response_safety, "monotonic", clock)


def test_generic_rest_success_body_rejects_slow_trickle(monkeypatch) -> None:
    clock = _MutableClock()
    response = _SlowTrickleResponse(clock)
    _bind_clock(monkeypatch, clock)
    monkeypatch.setattr(gh_rest_transport, "urlopen", lambda *_a, **_k: response)

    with pytest.raises(
        gh_rest_transport.RestNetworkError,
        match="exceeded the time limit",
    ):
        gh_rest_transport.request_with_retry(
            gh_rest_transport.RestRequest(method="GET", path="/slow"),
            token="ghs_secret",
            timeout_seconds=1.0,
            max_attempts=1,
        )

    assert response.read_calls == 2
    assert response.socket_timeouts == pytest.approx([1.0, 0.4])


def test_generic_rest_error_body_deadline_preserves_http_status(monkeypatch) -> None:
    clock = _MutableClock()
    body = _SlowTrickleResponse(clock)
    error = urllib.error.HTTPError(
        "https://api.github.com/slow",
        401,
        "Unauthorized",
        {},
        body,
    )
    _bind_clock(monkeypatch, clock)

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(gh_rest_transport, "urlopen", reject)
    with pytest.raises(gh_rest_transport.RestAuthError) as exc_info:
        gh_rest_transport.request_with_retry(
            gh_rest_transport.RestRequest(method="GET", path="/slow"),
            token="ghs_secret",
            timeout_seconds=1.0,
            max_attempts=1,
        )

    assert exc_info.value.status == 401
    assert exc_info.value.body == "GitHub REST error response could not be read"
    assert body.read_calls == 2


def test_installation_token_response_rejects_slow_trickle(monkeypatch) -> None:
    clock = _MutableClock()
    response = _SlowTrickleResponse(clock)
    _bind_clock(monkeypatch, clock)
    endpoint = validate_github_api_endpoint("https://api.github.com")

    with pytest.raises(GitHubAppTokenError, match="exceeded the time limit"):
        github_app_installation_token_transport.issue_installation_token_request(
            endpoint=endpoint,
            installation_id=123,
            app_jwt="app-jwt-secret",
            body={"repository_ids": [456]},
            opener=lambda *_args, **_kwargs: response,
            timeout_seconds=1.0,
        )

    assert response.read_calls == 2


def test_actions_log_download_rejects_slow_trickle(monkeypatch) -> None:
    clock = _MutableClock()
    responses: list[_SlowTrickleResponse] = []
    _bind_clock(monkeypatch, clock)
    monkeypatch.setattr(github_actions_logs, "_FETCH_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(github_actions_logs, "sleep", lambda _seconds: None)

    def open_slow(*_args, **_kwargs):
        response = _SlowTrickleResponse(clock)
        responses.append(response)
        return response

    monkeypatch.setattr(github_actions_logs, "urlopen", open_slow)
    with pytest.raises(gh_rest_transport.RestNetworkError):
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token="ghs_secret")

    assert len(responses) == 1
    assert responses[0].read_calls == 2


def test_verification_reader_rejects_slow_trickle() -> None:
    clock = _MutableClock()
    response = _SlowTrickleResponse(clock)

    with pytest.raises(
        GitHubAppVerificationResponseError,
        match="exceeded the time limit",
    ):
        read_bounded_verification_response(
            response,
            deadline=1.0,
            clock=clock,
        )

    assert response.read_calls == 2
