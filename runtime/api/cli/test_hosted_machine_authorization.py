from __future__ import annotations

from collections import deque

import pytest

from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpResponse,
    BoundedJsonHttpStatusError,
)


class _Clock:
    now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_browser_authorization_delivers_one_org_authority(monkeypatch) -> None:
    responses = deque(
        [
            BoundedJsonHttpResponse(
                payload={
                    "device_code": "device-secret",
                    "user_code": "ABCD-2345",
                    "verification_uri": "https://app.upyoke.com/machine",
                    "verification_uri_complete": (
                        "https://app.upyoke.com/machine?user_code=ABCD-2345"
                    ),
                    "expires_in": 600,
                    "interval": 2,
                },
                status=200,
                headers={},
            ),
            BoundedJsonHttpStatusError(202, {"error": "authorization_pending"}),
            BoundedJsonHttpResponse(
                payload={
                    "token": "tenant-actor-token",
                    "org": "acme",
                    "api_url": "https://app.upyoke.com/api/orgs/acme",
                },
                status=200,
                headers={},
            ),
        ]
    )
    seen = []

    def fake_request(request, **kwargs):
        seen.append((request.full_url, request.data, kwargs.get("sensitive_values")))
        result = responses.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(auth, "request_json", fake_request)
    clock = _Clock()
    pending = auth.start("https://app.upyoke.com")
    assert pending.user_code == "ABCD-2345"
    credential = auth.complete(
        pending,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert credential.api_url == "https://app.upyoke.com/api/orgs/acme"
    assert credential.org == "acme"
    assert credential.token == "tenant-actor-token"
    assert seen[1][2] == ("device-secret",)


def test_browser_authorization_rejects_cross_origin_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "request_json",
        lambda *_args, **_kwargs: BoundedJsonHttpResponse(
            payload={
                "device_code": "device-secret",
                "user_code": "ABCD-2345",
                "verification_uri": "https://evil.example/machine",
                "verification_uri_complete": "https://evil.example/machine?user_code=x",
                "expires_in": 600,
                "interval": 2,
            },
            status=200,
            headers={},
        ),
    )
    with pytest.raises(auth.HostedMachineAuthorizationError, match="unsafe browser"):
        auth.start("https://app.upyoke.com")


def test_browser_authorization_opens_complete_url_without_exposing_device_code(
    monkeypatch,
) -> None:
    pending = auth.PendingMachineAuthorization(
        platform_url="https://app.upyoke.com",
        device_code="device-secret",
        user_code="ABCD-2345",
        verification_uri="https://app.upyoke.com/machine",
        verification_uri_complete="https://app.upyoke.com/machine?user_code=ABCD-2345",
        expires_in=600,
        interval=2,
    )
    opened = []
    assert auth.open_browser(
        pending, browser_open=lambda url: opened.append(url) or True
    )
    assert opened == [pending.verification_uri_complete]
    assert "device-secret" not in repr(pending)
