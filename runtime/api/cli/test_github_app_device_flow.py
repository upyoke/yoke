from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.parse

import pytest

from yoke_cli.config import github_device_flow


class _Response:
    def __init__(self, payload: dict[str, Any], url: str) -> None:
        self.payload = payload
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self, size: int = -1) -> bytes:
        body = json.dumps(self.payload).encode("utf-8")
        return body[:size] if size >= 0 else body

    def geturl(self) -> str:
        return self.url


def test_device_flow_opens_browser_and_honors_pending_and_slow_down() -> None:
    responses = iter([
        {
            "device_code": "device-secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
        {"error": "authorization_pending"},
        {"error": "slow_down"},
        {
            "access_token": "access-secret",
            "expires_in": 28800,
            "refresh_token": "refresh-secret",
            "refresh_token_expires_in": 15552000,
        },
    ])
    requests: list[dict[str, list[str]]] = []
    sleeps: list[float] = []
    notices: list[dict[str, Any]] = []

    def opener(request, timeout):
        requests.append(urllib.parse.parse_qs(request.data.decode("utf-8")))
        return _Response(next(responses), request.full_url)

    result = github_device_flow.authorize(
        client_id="Iv1.local", web_url="https://github.com",
        opener=opener, browser_open=lambda url: url.endswith("/login/device"),
        notify=lambda event: notices.append(dict(event)),
        sleep=sleeps.append, monotonic=lambda: 0,
    )

    assert result.token_response["access_token"] == "access-secret"
    assert result.browser_opened is True
    assert sleeps == [5, 5, 10]
    assert requests[0] == {"client_id": ["Iv1.local"]}
    assert requests[-1]["grant_type"] == [
        "urn:ietf:params:oauth:grant-type:device_code"
    ]
    assert notices[0]["user_code"] == "ABCD-EFGH"
    rendered = repr(result)
    assert "device-secret" not in rendered
    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered


def test_device_flow_keeps_manual_details_when_browser_fails() -> None:
    responses = iter([
        {
            "device_code": "device-secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
        {
            "access_token": "access-secret",
            "expires_in": 28800,
            "refresh_token": "refresh-secret",
            "refresh_token_expires_in": 15552000,
        },
    ])
    notices: list[dict[str, Any]] = []

    result = github_device_flow.authorize(
        client_id="Iv1.local", web_url="https://github.com",
        opener=lambda request, timeout: _Response(
            next(responses), request.full_url,
        ),
        browser_open=lambda url: False,
        notify=lambda event: notices.append(dict(event)),
        sleep=lambda seconds: None, monotonic=lambda: 0,
    )

    assert result.browser_opened is False
    assert notices[-1] == {
        "phase": "device_browser",
        "browser_opened": False,
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 900,
        "interval": 5,
    }


def test_device_flow_rejects_cross_origin_verification_uri() -> None:
    browser_calls: list[str] = []
    payload = {
        "device_code": "device-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://evil.example/login/device",
        "expires_in": 900,
        "interval": 5,
    }

    try:
        github_device_flow.authorize(
            client_id="Iv1.local", web_url="https://github.com",
            opener=lambda request, timeout: _Response(
                payload, request.full_url,
            ),
            browser_open=lambda url: browser_calls.append(url),
            sleep=lambda seconds: None, monotonic=lambda: 0,
        )
    except github_device_flow.GitHubDeviceFlowError as exc:
        assert "crossed the configured web origin" in str(exc)
    else:
        raise AssertionError("expected cross-origin verification URI rejection")
    assert browser_calls == []


@pytest.mark.parametrize("field,value", [
    ("user_code", "[bold]spoof[/bold]"),
    ("user_code", "ABCD-\x1bGH"),
    ("verification_uri", "https://github.com/login/\x1b]2;spoof"),
    ("verification_uri", "https://github.com/" + "x" * 2_048),
])
def test_device_flow_rejects_hostile_public_authorization_fields(
    field: str, value: str,
) -> None:
    payload = {
        "device_code": "device-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 900,
        "interval": 5,
        field: value,
    }

    with pytest.raises(github_device_flow.GitHubDeviceFlowError):
        github_device_flow.authorize(
            client_id="Iv1.local",
            web_url="https://github.com",
            opener=lambda request, timeout: _Response(
                payload, request.full_url,
            ),
        )


def test_device_flow_disabled_error_teaches_app_registration_switches() -> None:
    payload = {
        "error": "device_flow_disabled",
        "error_description": "Device Flow is not enabled for this App",
    }

    try:
        github_device_flow.authorize(
            client_id="Iv1.local", web_url="https://github.com",
            opener=lambda request, timeout: _Response(
                payload, request.full_url,
            ),
        )
    except github_device_flow.GitHubDeviceFlowError as exc:
        message = str(exc)
        assert "Device Flow" in message
        assert "Expire user authorization tokens" in message
    else:
        raise AssertionError("expected disabled device-flow rejection")


def test_nonrefreshable_user_token_teaches_expiry_setting() -> None:
    responses = iter([
        {
            "device_code": "device-secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
        {"access_token": "access-secret", "expires_in": 28_800},
    ])

    try:
        github_device_flow.authorize(
            client_id="Iv1.local", web_url="https://github.com",
            opener=lambda request, timeout: _Response(
                next(responses), request.full_url,
            ),
            browser_open=lambda url: True,
            sleep=lambda seconds: None, monotonic=lambda: 0,
        )
    except github_device_flow.GitHubDeviceFlowError as exc:
        message = str(exc)
        assert "refreshable" in message
        assert "Expire user authorization tokens" in message
    else:
        raise AssertionError("expected nonrefreshable token rejection")


def test_device_endpoint_http_error_teaches_registration_prerequisites() -> None:
    def denied(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", hdrs=None, fp=None,
        )

    try:
        github_device_flow.authorize(
            client_id="Iv1.local", web_url="https://github.com", opener=denied,
        )
    except github_device_flow.GitHubDeviceFlowError as exc:
        message = str(exc)
        assert "Device Flow" in message
        assert "Expire user authorization tokens" in message
    else:
        raise AssertionError("expected device endpoint failure")


def test_device_invalid_utf8_is_a_typed_error() -> None:
    class _RawResponse(_Response):
        def read(self, size: int = -1) -> bytes:
            return b"\xff"

    with pytest.raises(github_device_flow.GitHubDeviceFlowError, match="not JSON"):
        github_device_flow.authorize(
            client_id="Iv1.local",
            web_url="https://github.com",
            opener=lambda request, timeout: _RawResponse(
                {}, request.full_url,
            ),
        )


def test_device_transport_reason_redacts_device_code() -> None:
    responses = iter([{
        "device_code": "device-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 900,
        "interval": 5,
    }])

    def opener(request, timeout):
        try:
            return _Response(next(responses), request.full_url)
        except StopIteration:
            raise urllib.error.URLError("refused device-secret ABCD-EFGH")

    with pytest.raises(github_device_flow.GitHubDeviceFlowError) as caught:
        github_device_flow.authorize(
            client_id="Iv1.local", web_url="https://github.com",
            opener=opener, browser_open=lambda url: False,
            sleep=lambda seconds: None, monotonic=lambda: 0,
        )
    assert "device-secret" not in str(caught.value)
    assert "ABCD-EFGH" not in str(caught.value)


def test_device_flow_does_not_request_after_expiry_sleep() -> None:
    clock = [0.0]
    requests: list[str] = []

    def opener(request, timeout):
        requests.append(request.full_url)
        return _Response({
            "device_code": "device-secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 5,
            "interval": 5,
        }, request.full_url)

    with pytest.raises(github_device_flow.GitHubDeviceFlowError, match="expired"):
        github_device_flow.authorize(
            client_id="Iv1.local",
            web_url="https://github.com",
            opener=opener,
            browser_open=lambda url: False,
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            monotonic=lambda: clock[0],
        )

    assert requests == ["https://github.com/login/device/code"]
