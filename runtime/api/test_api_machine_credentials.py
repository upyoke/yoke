"""HTTP enforcement for machine-bound relay credentials."""

from fastapi.testclient import TestClient

from yoke_core.api.main import app
from yoke_core.domain.api_tokens import TOKEN_PREFIX, mint_token


MACHINE_ID = "11111111-1111-4111-8111-111111111119"
OTHER_MACHINE_ID = "22222222-2222-4222-8222-222222222229"


def _envelope(function: str, payload: dict) -> dict:
    return {
        "function": function,
        "version": "v1",
        "actor": {"session_id": "machine-http-test"},
        "target": {"kind": "global"},
        "payload": payload,
    }


def test_http_relay_binding_and_retired_auth_are_typed(test_db) -> None:
    account = mint_token(test_db, actor_id=1, name="machine-connect-test")
    account_headers = {"Authorization": f"Bearer {account.raw_token}"}

    with TestClient(app) as client:
        registration = client.post(
            "/v1/functions/call",
            json=_envelope(
                "machine.register", {"machine_id": MACHINE_ID, "name": "HTTP machine"}
            ),
            headers=account_headers,
        )
        assert registration.status_code == 200
        credential = registration.json()["result"]["credential"]
        assert credential["status"] == "active"
        assert credential["token"].startswith(TOKEN_PREFIX)
        headers = {"Authorization": f"Bearer {credential['token']}"}

        mismatch = client.post(
            "/v1/functions/call",
            json=_envelope(
                "session_control.relay.claim", {"machine_id": OTHER_MACHINE_ID}
            ),
            headers=headers,
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["error"]["code"] == "machine_credential_mismatch"

        retirement = client.post(
            "/v1/functions/call",
            json=_envelope("machine.retire", {"machine_id": MACHINE_ID}),
            headers=account_headers,
        )
        assert retirement.status_code == 200
        assert retirement.json()["result"]["machine"]["retired_at"] is not None
        retired = client.post(
            "/v1/functions/call",
            json=_envelope("machine.list", {}),
            headers=headers,
        )
        assert retired.status_code == 401
        assert retired.json()["error"]["code"] == "machine_retired"
