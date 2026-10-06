"""Anonymous start/poll requests have independent transport-client budgets."""

from fastapi.testclient import TestClient
import pytest

from runtime.api import test_web_sign_in_door as door
from runtime.api.test_machine_authorization import IDENTITY
from yoke_contracts.machine_authorization import START_PATH, POLL_PATH
from yoke_core.domain import machine_authorization_limits as limits

_clean_oidc_env = door._clean_oidc_env
db_conn = door.db_conn
client = door.client
door_env = door.door_env
provider = door.provider


@pytest.mark.parametrize("path,operation", [(START_PATH, "start"), (POLL_PATH, "poll")])
def test_malformed_requests_count_and_headers_cannot_reset_budget(
    client, monkeypatch, path, operation
):
    monkeypatch.setattr(limits, operation.upper() + "_REQUESTS", 2)
    for identity in ("first", "second"):
        response = client.post(path, json={}, headers={"X-Forwarded-For": identity})
        assert response.status_code == 400
    limited = client.post(
        path,
        json={**IDENTITY, "device_code": "different"},
        headers={"X-Forwarded-For": "new"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"] == f"authorization_{operation}_rate_limited"
    assert 1 <= int(limited.headers["Retry-After"]) <= limits.RATE_WINDOW_SECONDS
    assert limited.headers["Cache-Control"] == "no-store"
    # An actual different transport client has its own budget; no code/body key
    # was needed to exhaust the first one, so unknown codes cannot bypass it.
    with TestClient(client.app, client=("192.0.2.44", 1234)) as other:
        assert other.post(path, json={}).status_code == 400


def test_start_limit_does_not_consume_poll_budget(client, monkeypatch, door_env):
    monkeypatch.setattr(limits, "START_REQUESTS", 1)
    started = client.post(START_PATH, json=IDENTITY).json()
    assert (
        client.post(START_PATH, json=IDENTITY).json()["error"]
        == "authorization_start_rate_limited"
    )
    pending = client.post(
        POLL_PATH, json={**IDENTITY, "device_code": started["device_code"]}
    )
    assert pending.status_code == 202
    assert pending.json()["error"] == "authorization_pending"


def test_start_pending_capacity_is_bound_to_peer_even_with_new_machine_ids(
    client, monkeypatch, door_env
):
    from uuid import uuid4

    monkeypatch.setattr(limits, "START_REQUESTS", 20)
    for _ in range(limits.CLIENT_PENDING_CODES):
        assert (
            client.post(
                START_PATH, json={**IDENTITY, "machine_id": str(uuid4())}
            ).status_code
            == 200
        )
    limited = client.post(START_PATH, json=IDENTITY)
    assert limited.status_code == 429
    assert limited.json()["error"] == "authorization_client_capacity"
    with TestClient(client.app, client=("192.0.2.44", 1234)) as other:
        assert other.post(START_PATH, json=IDENTITY).status_code == 200
