"""Hard wall-clock response deadlines across GitHub machine transports."""

from __future__ import annotations

import json

import pytest

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_app_user_api
from yoke_cli.config import github_device_flow
from yoke_cli.config import github_oauth_transport
from yoke_cli.config import github_publish_transport


class _Response:
    def __init__(self, payload: dict, *, url: str = "") -> None:
        self.body = json.dumps(payload).encode("utf-8")
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body[:size] if size >= 0 else self.body

    def geturl(self) -> str:
        return self.url


class _SlowResponse(_Response):
    def __init__(self, payload: dict, clock: list[float], advance: float, **kwargs):
        super().__init__(payload, **kwargs)
        self.clock = clock
        self.advance = advance

    def read1(self, size: int = -1) -> bytes:
        self.clock[0] += self.advance
        return self.body[:size] if size >= 0 else self.body


def test_discovery_slow_trickle_cannot_cross_aggregate_deadline() -> None:
    clock = [0.0]
    with pytest.raises(
        github_app_user_api.GitHubAppUserApiError,
        match="operation deadline",
    ):
        github_app_user_api.discover_access(
            api_url="https://api.github.com", access_token="access",
            opener=lambda request, timeout: _SlowResponse(
                {"id": 42, "login": "octocat"}, clock, 2.0,
                url=request.full_url,
            ),
            total_deadline_seconds=1.0,
            monotonic=lambda: clock[0],
        )


def test_device_poll_slow_trickle_expires_without_another_request() -> None:
    clock = [0.0]
    payloads = iter([
        ({
            "device_code": "device", "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 10, "interval": 5,
        }, False),
        ({"error": "authorization_pending"}, True),
    ])
    def opener(request, timeout):
        payload, slow = next(payloads)
        response_type = _SlowResponse if slow else _Response
        if slow:
            return response_type(payload, clock, 6.0, url=request.full_url)
        return response_type(payload, url=request.full_url)

    with pytest.raises(github_device_flow.GitHubDeviceFlowError, match="expired"):
        github_device_flow.authorize(
            client_id="Iv1.local", web_url="https://github.com",
            opener=opener,
            browser_open=lambda url: False,
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            monotonic=lambda: clock[0],
        )


def test_oauth_refresh_slow_trickle_releases_with_typed_deadline() -> None:
    clock = [0.0]
    with pytest.raises(
        github_oauth_transport.GitHubOAuthTransportError,
        match="operation deadline",
    ):
        github_oauth_transport.post_form(
            "https://github.com/login/oauth/access_token",
            {"refresh_token": "secret"},
            opener=lambda request, timeout: _SlowResponse(
                {}, clock, 2.0, url=request.full_url,
            ),
            timeout_seconds=1.0,
            monotonic=lambda: clock[0],
        )


def test_public_profile_slow_trickle_stops_at_selected_service_deadline() -> None:
    clock = [0.0]
    health_url = "https://stage.yoke.example/v1/health"
    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="operation deadline",
    ):
        github_app_public_profile.fetch(
            "https://stage.yoke.example",
            opener=lambda request, timeout: _SlowResponse(
                {"github_app": {"available": False}}, clock, 2.0,
                url=health_url,
            ),
            timeout_seconds=1.0,
            monotonic=lambda: clock[0],
        )


def test_publish_slow_trickle_returns_ambiguous_typed_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(
        github_publish_transport.time, "monotonic", lambda: clock[0],
    )
    monkeypatch.setattr(
        github_publish_transport,
        "_urlopen",
        lambda request, timeout: _SlowResponse({}, clock, 21.0),
    )
    with pytest.raises(
        github_publish_transport.GitHubPublishError,
        match="operation deadline",
    ):
        github_publish_transport.request_json(
            "https://api.github.com", "/user/repos", "access",
            method="POST", body={"name": "widget"},
        )
