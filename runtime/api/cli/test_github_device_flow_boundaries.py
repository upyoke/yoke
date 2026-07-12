"""Timing and direct-transport boundaries for GitHub device authorization."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_github_app_device_flow import _Response
from yoke_cli.config import github_device_flow


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires_in", 901),
        ("interval", 61),
        ("expires_in", 10**100),
    ],
)
def test_device_flow_rejects_unbounded_authorization_timing(
    field: str,
    value: int,
) -> None:
    payload = {
        "device_code": "device-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 900,
        "interval": 5,
        field: value,
    }
    with pytest.raises(
        github_device_flow.GitHubDeviceFlowError,
        match="timing exceeds supported limits",
    ):
        github_device_flow.authorize(
            client_id="Iv1.local",
            web_url="https://github.com",
            opener=lambda request, timeout: _Response(
                payload,
                request.full_url,
            ),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires_in", 86_401),
        ("refresh_token_expires_in", 31_622_401),
        ("refresh_token_expires_in", 10**100),
    ],
)
def test_device_flow_rejects_unbounded_token_timing(
    field: str,
    value: int,
) -> None:
    responses = iter(
        [
            {
                "device_code": "device-secret",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
            {
                "access_token": "access-secret",
                "expires_in": 28_800,
                "refresh_token": "refresh-secret",
                "refresh_token_expires_in": 15_552_000,
                field: value,
            },
        ]
    )
    with pytest.raises(
        github_device_flow.GitHubDeviceFlowError,
        match="expiring, refreshable",
    ):
        github_device_flow.authorize(
            client_id="Iv1.local",
            web_url="https://github.com",
            opener=lambda request, timeout: _Response(
                next(responses),
                request.full_url,
            ),
            browser_open=lambda url: False,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("socket detail must not leak"),
        OSError("platform detail must not leak"),
    ],
)
def test_device_flow_wraps_direct_transport_errors_without_details(
    failure: Exception,
) -> None:
    with pytest.raises(github_device_flow.GitHubDeviceFlowError) as caught:
        github_device_flow.authorize(
            client_id="Iv1.local",
            web_url="https://github.com",
            opener=lambda request, timeout: (_ for _ in ()).throw(failure),
        )
    message = str(caught.value)
    assert "could not be reached" in message
    assert "must not leak" not in message
