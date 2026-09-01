"""A refused loopback relay answers immediately instead of retrying for 95s."""

from __future__ import annotations

import urllib.error

import pytest

from runtime.api.cli.test_yoke_transport import _request
from yoke_cli.transport import https as yoke_transport
from yoke_cli.transport.https import HttpsConnection, relay_https
from yoke_cli.transport.https_retry_policy import (
    CONNECTION_ATTEMPTS,
    connection_refusal_is_conclusive,
    should_retry_connection,
)


def _refusal() -> urllib.error.URLError:
    return urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))


@pytest.mark.parametrize(
    "api_url",
    ["http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"],
)
def test_loopback_refusal_is_conclusive(api_url: str) -> None:
    assert connection_refusal_is_conclusive(api_url, _refusal()) is True
    assert should_retry_connection(0, api_url, _refusal()) is False


@pytest.mark.parametrize(
    ("api_url", "error"),
    [
        # A name can front a fleet with one box restarting.
        ("https://app.upyoke.com/api", urllib.error.URLError(
            ConnectionRefusedError(61, "Connection refused"))),
        # A routable address that refused is still worth another ask.
        ("http://10.0.0.4:8765", urllib.error.URLError(
            ConnectionRefusedError(61, "Connection refused"))),
        # Loopback that timed out is a slow server, not a missing one.
        ("http://127.0.0.1:8765", TimeoutError()),
    ],
)
def test_other_connection_failures_keep_the_retry_budget(
    api_url: str, error: BaseException,
) -> None:
    assert connection_refusal_is_conclusive(api_url, error) is False
    assert should_retry_connection(0, api_url, error) is True


def test_spent_budget_stops_regardless_of_conclusiveness() -> None:
    assert should_retry_connection(CONNECTION_ATTEMPTS - 1) is False


def test_relay_refuses_a_refused_loopback_on_the_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    slept: list[float] = []

    def fake_urlopen(req, timeout=None):
        attempts.append(req.full_url)
        raise _refusal()

    monkeypatch.setattr(yoke_transport, "open_no_redirect", fake_urlopen)
    response = relay_https(
        _request(),
        HttpsConnection(api_url="http://127.0.0.1:8765", token="actor"),
        sleep=slept.append,
    )

    assert len(attempts) == 1
    assert slept == []
    assert response.success is False
    assert response.error.code == "https_transport_failed"
    assert "could not reach" in response.error.message
    assert "retrying will not help" in response.error.recovery_hint
    assert "docker compose up -d" in response.error.recovery_hint


def test_relay_still_retries_a_refused_named_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    slept: list[float] = []

    def fake_urlopen(req, timeout=None):
        attempts.append(req.full_url)
        raise _refusal()

    monkeypatch.setattr(yoke_transport, "open_no_redirect", fake_urlopen)
    response = relay_https(
        _request(),
        HttpsConnection(api_url="https://api.example", token="actor"),
        sleep=slept.append,
    )

    assert len(attempts) == CONNECTION_ATTEMPTS
    assert len(slept) == CONNECTION_ATTEMPTS - 1
    assert response.success is False
    assert "Retrying is the repair" in response.error.recovery_hint
