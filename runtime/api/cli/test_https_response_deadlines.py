"""Absolute-deadline coverage for hosted CLI response bodies."""

from __future__ import annotations

import json
import urllib.error

import pytest

from runtime.api.cli.https_relay_security_test_support import (
    CONNECTION,
    FakeResponse,
    envelope,
    sensitive_request,
)
from yoke_cli.transport import https as relay_module
from yoke_cli.transport import response_deadline_read
from yoke_cli.transport import runner_fleet_token
from yoke_cli.transport.https import HttpsConnection, TransportError


class _MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _SlowTrickleResponse:
    status = 200

    def __init__(
        self,
        clock: _MutableClock,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.clock = clock
        self.headers = dict(headers or {})
        self.read_calls = 0
        self.socket_timeouts: list[float] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self) -> None:
        return None

    def geturl(self) -> str:
        return "https://api.upyoke.com/v1/projects/platform/runner-fleet-token"

    def read(self, _size: int = -1) -> bytes:
        raise AssertionError("network responses must use incremental reads")

    def read1(self, _size: int = -1) -> bytes:
        self.read_calls += 1
        self.clock.advance(0.6)
        return b"{" if self.read_calls == 1 else b"}"

    def settimeout(self, seconds: float) -> None:
        self.socket_timeouts.append(seconds)


class _Opener:
    def __init__(self, response: _SlowTrickleResponse) -> None:
        self.response = response

    def open(self, _request, timeout):
        assert timeout == 1.0
        return self.response


def _bind_clock(monkeypatch, clock: _MutableClock) -> None:
    monkeypatch.setattr(response_deadline_read, "monotonic", clock)


def _assert_relay_deadline(response) -> None:
    assert response.success is False
    assert response.error is not None
    assert response.error.code == "https_transport_failed"
    assert "exceeded the time limit" in response.error.message


def test_https_relay_success_body_rejects_slow_trickle(monkeypatch) -> None:
    clock = _MutableClock()
    response_stream = _SlowTrickleResponse(clock)
    _bind_clock(monkeypatch, clock)
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda *_args, **_kwargs: response_stream,
    )

    response = relay_module.relay_https(
        sensitive_request(),
        CONNECTION,
        timeout_s=1.0,
    )

    _assert_relay_deadline(response)
    assert response_stream.read_calls == 2
    assert response_stream.socket_timeouts == pytest.approx([1.0, 0.4])


def test_https_relay_default_opener_uses_bounded_caller_owned_post(
    monkeypatch,
) -> None:
    seen = {}

    def bounded(request, *, deadline, replay_safe, allow_loopback_http, opener):
        seen.update(
            request=request,
            deadline=deadline,
            replay_safe=replay_safe,
            allow_loopback_http=allow_loopback_http,
            opener=opener,
        )
        return FakeResponse(envelope(result={"ok": True}))

    monkeypatch.setattr(relay_module, "open_bounded_request", bounded)
    response = relay_module.relay_https(
        sensitive_request(),
        CONNECTION,
        timeout_s=1.0,
    )

    assert response.success is True
    assert response.result == {"ok": True}
    assert seen["request"].get_method() == "POST"
    assert seen["replay_safe"] is False
    assert seen["allow_loopback_http"] is True
    assert seen["opener"] is None


def test_https_relay_error_body_rejects_slow_trickle(monkeypatch) -> None:
    clock = _MutableClock()
    error_stream = _SlowTrickleResponse(clock)
    _bind_clock(monkeypatch, clock)

    def reject(request, timeout=None):
        del timeout
        raise urllib.error.HTTPError(
            request.full_url,
            502,
            "Bad Gateway",
            {},
            error_stream,
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)
    response = relay_module.relay_https(
        sensitive_request(),
        CONNECTION,
        timeout_s=1.0,
    )

    _assert_relay_deadline(response)
    assert error_stream.read_calls == 2


def test_runner_fleet_token_response_rejects_slow_trickle(monkeypatch) -> None:
    clock = _MutableClock()
    response = _SlowTrickleResponse(clock, headers={"Cache-Control": "no-store"})
    _bind_clock(monkeypatch, clock)
    monkeypatch.setattr(runner_fleet_token, "_OPENER", _Opener(response))
    intent = json.dumps(
        {
            "schema": 1,
            "authority": {"repo": "upyoke/platform"},
            "sha256": "a" * 64,
        }
    )

    with pytest.raises(TransportError, match="exceeded the time limit"):
        runner_fleet_token.fetch_runner_fleet_token(
            HttpsConnection("https://api.upyoke.com", "infrastructure-token"),
            project="platform",
            authority_intent=intent,
            timeout_seconds=1.0,
        )

    assert response.read_calls == 2
