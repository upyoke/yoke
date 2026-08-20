"""A relay that did not answer is asked again; one that answered is not.

The failure these cover ran for weeks: a momentary network condition or a
box restarting mid-release reached the caller as a hard error, and the
advice attached to it told operators to inspect an env and credential that
were both fine.
"""

from __future__ import annotations

import http.client
import io
import urllib.error

import pytest

from runtime.api.cli.https_relay_security_test_support import (
    CONNECTION,
    FakeResponse,
    envelope,
    sensitive_request,
)
from yoke_cli.transport import https as relay_module
from yoke_cli.transport import https_retry_policy


@pytest.fixture(autouse=True)
def _no_telemetry(monkeypatch):
    """Outcome recording has its own module and its own tests."""
    monkeypatch.setattr(relay_module, "record_outcome", lambda *_a, **_k: None)


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.example/v1/functions/call",
        status,
        "boom",
        {},  # type: ignore[arg-type]
        io.BytesIO(body),
    )


def _relay(monkeypatch, openers, sleeps):
    calls = {"count": 0}

    def _open(_request, *, deadline, timeout_s):
        index = calls["count"]
        calls["count"] += 1
        outcome = openers[min(index, len(openers) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(relay_module, "_open_function_relay", _open)
    response = relay_module.relay_https(
        sensitive_request(), CONNECTION, sleep=sleeps.append,
    )
    return response, calls["count"]


def test_a_dropped_connection_is_retried_until_it_lands(monkeypatch) -> None:
    sleeps: list[float] = []
    response, opens = _relay(
        monkeypatch,
        [
            ConnectionResetError("connection reset by peer"),
            FakeResponse(envelope(result={"ok": True})),
        ],
        sleeps,
    )

    assert response.success is True
    assert opens == 2
    assert sleeps == [https_retry_policy.connection_backoff_seconds(0)]


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionResetError("reset"),
        TimeoutError("timed out"),
        urllib.error.URLError("name or service not known"),
        http.client.HTTPException("protocol error"),
    ],
    ids=["reset", "timeout", "name-resolution", "protocol"],
)
def test_every_connection_level_failure_spends_the_whole_budget(
    monkeypatch, failure,
) -> None:
    sleeps: list[float] = []
    response, opens = _relay(monkeypatch, [failure], sleeps)

    assert opens == https_retry_policy.CONNECTION_ATTEMPTS
    assert len(sleeps) == https_retry_policy.CONNECTION_ATTEMPTS - 1
    assert response.success is False
    assert response.error is not None
    assert (
        f"after {https_retry_policy.CONNECTION_ATTEMPTS} attempts"
        in response.error.message
    )


def test_a_gateway_page_from_a_restarting_box_is_retried(monkeypatch) -> None:
    sleeps: list[float] = []
    response, opens = _relay(
        monkeypatch,
        [
            _http_error(503, b"<html>service unavailable</html>"),
            FakeResponse(envelope(result={"ok": True})),
        ],
        sleeps,
    )

    assert response.success is True
    assert opens == 2
    assert sleeps == [https_retry_policy.connection_backoff_seconds(0)]


def test_a_rejection_about_this_request_is_never_retried(monkeypatch) -> None:
    """401, 403 and a malformed payload are answers, not outages."""
    for status in (400, 401, 403, 422):
        sleeps: list[float] = []
        response, opens = _relay(
            monkeypatch, [_http_error(status, b"nope")], sleeps,
        )
        assert opens == 1, status
        assert sleeps == [], status
        assert response.success is False


def test_a_five_hundred_carrying_a_real_envelope_still_wins(
    monkeypatch,
) -> None:
    """Retryability is read from the status, before the body is touched.

    Reading first to find out whether it was worth retrying would spend the
    response's one bounded read on a reply about to be asked for again. So a
    5xx that does carry a real envelope is retried and only parsed once the
    budget runs out — the server's answer still wins, it just arrives after
    the attempts a gateway page would have needed.
    """
    sleeps: list[float] = []
    body = envelope(
        success=False,
        error={"code": "handler_exploded", "message": "boom"},
    )
    response, opens = _relay(monkeypatch, [_http_error(500, body)], sleeps)

    assert opens == https_retry_policy.CONNECTION_ATTEMPTS
    assert response.error is not None
    assert response.error.code == "handler_exploded"


def test_the_refusal_stops_blaming_the_operators_configuration(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    response, _opens = _relay(
        monkeypatch, [ConnectionResetError("reset")], sleeps,
    )

    assert response.error is not None
    hint = response.error.recovery_hint or ""
    assert "yoke status" not in hint
    assert "config.json" not in hint
    assert "not implicated" in hint
    assert "may or may not have been applied" in hint


def test_every_attempt_carries_the_same_request_id(monkeypatch) -> None:
    """The repeat is only safe because the ledger can recognize it."""
    bodies: list[bytes] = []

    def _open(request, *, deadline, timeout_s):
        bodies.append(request.data)
        if len(bodies) < 2:
            raise ConnectionResetError("reset")
        return FakeResponse(envelope(result={"ok": True}))

    monkeypatch.setattr(relay_module, "_open_function_relay", _open)
    relay_module.relay_https(sensitive_request(), CONNECTION, sleep=lambda _s: None)

    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
