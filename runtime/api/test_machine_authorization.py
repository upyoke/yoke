"""A second engineer connects through real OIDC and personal approval."""

import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from runtime.api import test_web_sign_in_door as door
from runtime.api.test_self_host_workbench import _call
from yoke_contracts.machine_authorization import (
    START_PATH,
    POLL_PATH,
    APPROVAL_RETURN_COOKIE,
    POLL_OUTCOMES,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers

_clean_oidc_env = door._clean_oidc_env
db_conn = door.db_conn
client = door.client
door_env = door.door_env
provider = door.provider

MACHINE_ID = "762fb8a5-7a6f-43e0-ae85-9665af3fe871"
IDENTITY = {"machine_id": MACHINE_ID, "machine_name": "Second engineer's laptop"}


def test_oidc_member_approves_machine_without_host_minted_token(
    db_conn, client, door_env, provider
):
    register_all_handlers()
    door._enable_domain_admission(db_conn, domain="example.com")
    assert client.get(START_PATH).json() == {"device_code": True}
    started = client.post(START_PATH, json=IDENTITY)
    assert started.status_code == 200, started.text
    _validate_wire(started, "MachineAuthorizationStarted")
    pending = started.json()
    assert pending["verification_uri_complete"].startswith(
        "http://testserver/machine-approval/"
    )
    signed_out = client.get(pending["verification_uri_complete"])
    assert "Sign in" in signed_out.text
    assert client.cookies.get(APPROVAL_RETURN_COOKIE)
    signed_in = door._sign_in(
        client, provider, email="second@example.com", sub="second-engineer"
    )
    assert signed_in.status_code == 303, signed_in.text
    assert signed_in.headers["location"].endswith(pending["user_code"])
    assert not client.cookies.get(APPROVAL_RETURN_COOKIE)
    assert "mountUniverseApp" in client.get(signed_in.headers["location"]).text
    polled = client.post(
        POLL_PATH, json={"device_code": pending["device_code"], **IDENTITY}
    )
    assert polled.status_code == 202
    _validate_wire(polled, "MachineAuthorizationPending")
    code = {"code": pending["user_code"]}
    inspected = _call(client, "machine_authorization.get", code)
    assert inspected.status_code == 200, inspected.text
    assert (
        inspected.json()["result"]["authorization"]["machine"]
        == IDENTITY["machine_name"]
    )
    refused = _call(
        client,
        "machine_authorization.resolve",
        {**code, "action": "approve"},
        Origin="https://attacker.example",
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "cross_origin_refused"
    approved = _call(
        client, "machine_authorization.resolve", {**code, "action": "approve"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["success"] is True
    delivered = client.post(
        POLL_PATH, json={"device_code": pending["device_code"], **IDENTITY}
    )
    assert delivered.status_code == 200, delivered.text
    _validate_wire(delivered, "MachineAuthorizationApproved")
    credential = delivered.json()
    identity = client.get(
        "/v1/auth/identity", headers={"Authorization": "Bearer " + credential["token"]}
    )
    assert identity.status_code == 200, identity.text
    assert credential["api_url"] == "http://testserver"
    assert (
        client.post(
            POLL_PATH, json={"device_code": pending["device_code"], **IDENTITY}
        ).status_code
        == 410
    )
    row = db_conn.execute(
        "SELECT owner_actor_id FROM machines WHERE machine_id=%s", (MACHINE_ID,)
    ).fetchone()
    assert row is not None
    owner = row[0]
    admin = db_conn.execute(
        "SELECT 1 FROM actor_org_roles ar JOIN roles r ON r.id=ar.role_id WHERE ar.actor_id=%s AND r.name='admin'",
        (owner,),
    ).fetchone()
    assert admin is None


def test_no_company_sign_in_teaches_token_connection(client):
    assert client.get(START_PATH).json() == {"device_code": False}
    denied = client.post(START_PATH, json=IDENTITY)
    assert denied.status_code == 409
    assert denied.json()["error"] == "oidc_not_configured"
    assert "--token-stdin" in denied.json()["message"]


def test_partial_oidc_config_is_named(client, monkeypatch):
    monkeypatch.setenv("YOKE_OIDC_ISSUER", "https://issuer.example")
    denied = client.get(START_PATH)
    assert denied.status_code == 503
    assert denied.json()["error"] == "oidc_misconfigured"


def test_invalid_machine_identity_and_unknown_device_code_are_named(client, door_env):
    invalid = client.post(
        START_PATH, json={"machine_id": "invalid", "machine_name": "laptop"}
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "machine_identity_required"
    unknown = client.post(POLL_PATH, json={"device_code": "unknown", **IDENTITY})
    assert unknown.status_code == 410
    assert unknown.json()["error"] == "authorization_expired"


def _validate_wire(response, model):
    schema = json.loads(
        files("yoke_contracts")
        .joinpath("machine_authorization.schema.v1.json")
        .read_text()
    )
    Draft202012Validator({**schema, "$ref": f"#/$defs/{model}"}).validate(
        response.json()
    )


@pytest.mark.parametrize("error", POLL_OUTCOMES)
def test_poll_route_emits_schema_outcomes(client, door_env, monkeypatch, error):
    from yoke_core.api.routes import machine_authorization as route

    status, model = POLL_OUTCOMES[error]

    def refuse(*args, **kwargs):
        raise route.codes.MachineAuthorizationError(
            error, "restart or retry connection", status
        )

    if status == 429:
        monkeypatch.setattr(
            route,
            "_admit",
            lambda *a: route._error(
                error, "retry after Retry-After", status, retry_after=7
            ),
        )
    else:
        monkeypatch.setattr(route.codes, "poll", refuse)
    response = client.post(POLL_PATH, json={"device_code": "secret", **IDENTITY})
    assert response.status_code == status
    _validate_wire(response, model.__name__)
    assert response.headers["Cache-Control"] == "no-store"
    if status == 429:
        assert response.headers["Retry-After"] == "7"


def test_invalid_server_success_is_named_without_disclosing_credentials(
    client, door_env, monkeypatch
):
    from yoke_core.api.routes import machine_authorization as route

    monkeypatch.setattr(
        route.codes, "poll", lambda *a, **k: {"token": "private-credential"}
    )
    response = client.post(POLL_PATH, json={"device_code": "secret", **IDENTITY})
    assert response.status_code == 500
    _validate_wire(response, "MachineAuthorizationRefused")
    assert "authorization_response_invalid" in response.text
    assert "private-credential" not in response.text
