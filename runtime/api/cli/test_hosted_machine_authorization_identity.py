from __future__ import annotations

from collections import deque
import json
import uuid

import pytest

from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpResponse,
    BoundedJsonHttpStatusError,
)


MACHINE_ID = "8bea37d8-e2d5-4e4d-96c4-cfc53d9dbe5f"


class _Clock:
    now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _pending() -> auth.PendingMachineAuthorization:
    return auth.PendingMachineAuthorization(
        platform_url="https://app.upyoke.com",
        device_code="device-secret",
        user_code="ABCD-2345",
        verification_uri="https://app.upyoke.com/connect",
        verification_uri_complete="https://app.upyoke.com/connect?user_code=ABCD-2345",
        expires_in=60,
        interval=1,
    )


def _approved() -> BoundedJsonHttpResponse:
    return BoundedJsonHttpResponse(
        payload={
            "token": "machine-token",
            "org": "acme",
            "api_url": "https://app.upyoke.com/api/orgs/acme",
        },
        status=200,
        headers={},
    )


def test_poll_and_reconnect_reuse_canonical_machine_identity(
    monkeypatch, tmp_path
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    monkeypatch.setattr(auth, "machine_display_name", lambda: "Build Host")
    responses = deque(
        [
            BoundedJsonHttpResponse(
                payload={"error": "authorization_pending"},
                status=202,
                headers={},
            ),
            _approved(),
            _approved(),
        ]
    )
    requests: list[dict[str, str]] = []

    def fake_request(request, **_kwargs):
        requests.append(json.loads(request.data))
        return responses.popleft()

    monkeypatch.setattr(auth, "request_json", fake_request)
    for _ in range(2):
        clock = _Clock()
        credential = auth.complete(
            _pending(), sleep=clock.sleep, monotonic=clock.monotonic
        )
        assert credential.token == "machine-token"

    configured_id = json.loads(config_path.read_text(encoding="utf-8"))["machine_id"]
    assert str(uuid.UUID(configured_id)) == configured_id
    assert (
        requests
        == [
            {
                "device_code": "device-secret",
                "machine_id": configured_id,
                "machine_name": "Build Host",
            },
        ]
        * 3
    )


def test_missing_machine_identity_refuses_before_poll(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    monkeypatch.setattr(
        auth,
        "request_json",
        lambda *_args, **_kwargs: pytest.fail("poll must not run without identity"),
    )

    with pytest.raises(
        auth.HostedMachineAuthorizationError,
        match="machine_identity_required.*create or restore",
    ):
        auth.complete(_pending())


def test_server_identity_refusal_names_recovery(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"machine_id": MACHINE_ID}), encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    monkeypatch.setattr(auth, "machine_display_name", lambda: "Build Host")
    monkeypatch.setattr(
        auth,
        "request_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BoundedJsonHttpStatusError(400, {"error": "machine_identity_required"})
        ),
    )
    clock = _Clock()

    with pytest.raises(
        auth.HostedMachineAuthorizationError,
        match="machine_identity_required.*yoke status",
    ):
        auth.complete(_pending(), sleep=clock.sleep, monotonic=clock.monotonic)
