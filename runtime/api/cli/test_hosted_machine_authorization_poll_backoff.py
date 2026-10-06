"""Poll throttling preserves one-time authorization and its wait boundaries."""

import io
import json
import urllib.error

import pytest

from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.transport.bounded_json_http import BoundedJsonHttpResponse

ORIGIN = "https://team.example"


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def machine_identity(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_machine_identity",
        lambda: {"machine_id": "test-machine", "machine_name": "laptop"},
    )


def _pending():
    return auth.PendingMachineAuthorization(
        platform_url=ORIGIN,
        device_code="same-device-secret",
        user_code="CODE",
        verification_uri=ORIGIN + "/machine/approve",
        verification_uri_complete=ORIGIN + "/machine/approve/CODE",
        expires_in=60,
        interval=2,
        self_host=True,
    )


def _response(request, status, payload, headers):
    response = io.BytesIO(json.dumps(payload).encode())
    response.status = status
    response.headers = headers
    response.geturl = lambda: request.full_url
    return response


@pytest.mark.parametrize("http_error", [True, False])
@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [("7", 7), ("Thu, 01 Jan 1970 00:16:47 GMT", 7)],
)
def test_poll_throttling_honors_headers_and_keeps_code(
    monkeypatch, http_error, retry_after, expected_delay
):
    clock = _Clock()
    seen = []
    monkeypatch.setattr(auth.time, "time", lambda: 1000)

    def opener(request, timeout):
        seen.append((clock.now, request.full_url, json.loads(request.data)))
        if len(seen) == 1:
            payload = {"error": "authorization_poll_rate_limited"}
            headers = {"Retry-After": retry_after}
            if http_error:
                raise urllib.error.HTTPError(
                    request.full_url,
                    429,
                    "Too Many Requests",
                    headers,
                    io.BytesIO(json.dumps(payload).encode()),
                )
            return _response(request, 429, payload, headers)
        return _response(
            request,
            200,
            {"token": "machine-token", "org": "team", "api_url": ORIGIN},
            {},
        )

    credential = auth.complete(
        _pending(), opener=opener, sleep=clock.sleep, monotonic=clock.monotonic
    )
    assert credential.token == "machine-token"
    assert clock.waits == [2, expected_delay]
    assert [entry[0] for entry in seen] == [2, 2 + expected_delay]
    assert all(entry[1] == ORIGIN + auth.POLL_PATH for entry in seen)
    assert all(entry[2]["device_code"] == "same-device-secret" for entry in seen)
    assert seen[0][2] == seen[1][2]


@pytest.mark.parametrize("retry_after", [None, "invalid", "NaN", "inf", "-5", "0"])
def test_unusable_poll_retry_delay_preserves_normal_interval(monkeypatch, retry_after):
    clock = _Clock()
    answers = iter(
        [
            BoundedJsonHttpResponse(
                {"error": "authorization_poll_rate_limited"},
                429,
                {} if retry_after is None else {"retry-after": retry_after},
            ),
            BoundedJsonHttpResponse(
                {"token": "token", "org": "team", "api_url": ORIGIN}, 200, {}
            ),
        ]
    )
    monkeypatch.setattr(auth, "request_json", lambda *a, **k: next(answers))
    auth.complete(_pending(), sleep=clock.sleep, monotonic=clock.monotonic)
    assert clock.waits == [2, 2]


@pytest.mark.parametrize("cancelled", [False, True])
def test_poll_backoff_preserves_expiry_and_cancellation(monkeypatch, cancelled):
    clock = _Clock()
    calls = []

    def limited(*args, **kwargs):
        calls.append(True)
        return BoundedJsonHttpResponse(
            {"error": "authorization_poll_rate_limited"}, 429, {"retry-after": "120"}
        )

    monkeypatch.setattr(auth, "request_json", limited)
    error = (
        auth.HostedMachineAuthorizationCancelled
        if cancelled
        else auth.HostedMachineAuthorizationError
    )
    with pytest.raises(error, match="cancelled" if cancelled else "expired"):
        auth.complete(
            _pending(),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            cancelled=lambda: cancelled and len(clock.waits) > 1,
        )
    assert clock.waits == [2, 58]
    assert calls == [True]
