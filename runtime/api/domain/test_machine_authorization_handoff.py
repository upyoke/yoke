"""Hosted ingress preserves code identity and personal credential delivery."""

import hashlib
from contextlib import contextmanager
from datetime import timedelta

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection
from runtime.api.domain.machine_registry_test_support import MACHINE_ID
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain import machine_authorization_codes as codes
from yoke_core.domain import machine_authorization_decisions as decisions
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers.machine_authorization_handoff import handle_handoff
from yoke_core.domain.machine_authorization_handoff import handoff
from yoke_core.domain.machine_authorization_schema import (
    create_machine_authorization_table,
)
from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        create_auth_tables(value)
        create_external_identity_tables(value)
        ensure_machine_registry_schema(value)
        create_machine_authorization_table(value)
        value.execute(
            "INSERT INTO organizations (id,slug,name,created_at) VALUES (2, 'chosen', 'Chosen', 'now')"
        )
        value.execute("INSERT INTO actor_org_roles VALUES (6, 2, 5, 'now')")
        value.execute("INSERT INTO actor_org_roles VALUES (1, 2, 4, 'now')")
        value.commit()
        yield value


@pytest.fixture()
def registry():
    reset_registry_for_tests()
    register_all_handlers()
    yield
    reset_registry_for_tests()


def payload(**updates):
    return {
        "device_code_sha256": hashlib.sha256(b"hosted-device-secret").hexdigest(),
        "user_code": "K7F2",
        "machine_id": MACHINE_ID,
        "machine_name": "Laptop",
        "platform": "Linux",
        "expires_at": format_instant(utc_now() + timedelta(minutes=10)),
        "org_id": 2,
        **updates,
    }


def request(body, actor_id=6):
    return FunctionCallRequest.model_validate(
        {
            "function": "machine_authorization.handoff",
            "version": "v1",
            "request_id": "hosted-handoff",
            "actor": {"actor_id": str(actor_id), "session_id": "hosted-service"},
            "target": {"kind": "global"},
            "payload": body,
        }
    )


def test_registered_handoff_then_approval_and_poll_uses_selected_org(
    conn, registry, monkeypatch
):
    @contextmanager
    def connect():
        yield conn

    monkeypatch.setattr(
        "yoke_core.domain.handlers.machine_authorization.db_helpers.connect", connect
    )
    body = payload()
    entry = lookup("machine_authorization.handoff")
    assert entry.minimum_serving_version == "next-release"
    assert "service_token_required" in entry.guardrails
    assert check_dispatch_permission(conn, entry, request(body)).error is None
    result = handle_handoff(request(body))
    assert result.primary_success
    assert result.result_payload["authorization"]["user_code"] == "K7F2"
    assert decisions.inspect(conn, code="K7F2", actor_id=1)["machine"] == "Laptop"
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_pending"):
        codes.poll(
            conn,
            device_code="hosted-device-secret",
            machine_id=MACHINE_ID,
            machine_name="Laptop",
            origin="https://team.example",
        )
    decisions.resolve(conn, code="K7F2", actor_id=1, action="approve")
    credential = codes.poll(
        conn,
        device_code="hosted-device-secret",
        machine_id=MACHINE_ID,
        machine_name="Laptop",
        origin="https://team.example",
    )
    assert credential["org"] == "chosen"
    assert credential["token"]
    assert tuple(
        conn.execute("SELECT actor_id,machine_id FROM api_tokens").fetchone()
    ) == (1, MACHINE_ID)
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_consumed"):
        codes.poll(
            conn,
            device_code="hosted-device-secret",
            machine_id=MACHINE_ID,
            machine_name="Laptop",
            origin="https://team.example",
        )


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"device_code_sha256": "a" * 64}, "match_code_taken"),
        ({"user_code": "Z9Q2"}, "device_code_taken"),
    ],
)
def test_collisions_refuse_without_replacing_original(conn, updates, reason):
    body = payload()
    handoff(conn, **body, actor_id=6)
    with pytest.raises(codes.MachineAuthorizationError) as error:
        handoff(conn, **{**body, **updates}, actor_id=6)
    assert error.value.code == reason
    assert "issue a new" in str(error.value)
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"expires_at": "2000-01-01T00:00:00Z"}, "authorization_expired"),
        ({"expires_at": "2026-01-01"}, "authorization_expiry_invalid"),
        ({"machine_id": "invalid"}, "authorization_handoff_invalid"),
        ({"org_id": 999}, "authorization_org_unknown"),
    ],
)
def test_invalid_handoff_creates_no_request(conn, updates, reason):
    with pytest.raises(codes.MachineAuthorizationError) as error:
        handoff(conn, **payload(**updates), actor_id=6)
    assert error.value.code == reason
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("actor_id", [1, 5])
def test_member_and_admin_cannot_handoff(conn, actor_id):
    with pytest.raises(codes.MachineAuthorizationError, match="permission_denied"):
        handoff(conn, **payload(), actor_id=actor_id)


def test_service_cannot_target_an_org_without_its_grant(conn):
    conn.execute("DELETE FROM actor_org_roles WHERE actor_id=6 AND org_id=2")
    with pytest.raises(codes.MachineAuthorizationError, match="permission_denied"):
        handoff(conn, **payload(), actor_id=6)


def test_service_guard_rejects_member_token(conn, registry):
    from yoke_core.api.http_auth import HttpAuthContext
    from yoke_core.api.routes.functions import _service_token_guard_response

    entry = lookup("machine_authorization.handoff")
    for actor_id in (1, 5):
        denied = _service_token_guard_response(
            request(payload(), actor_id).model_dump(),
            entry,
            HttpAuthContext(token_id=1, actor_id=actor_id, token_name="hosted-service"),
            conn=conn,
        )
        assert denied.error.code == "permission_denied"


def test_handoff_shares_pending_capacity(conn, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.machine_authorization_handoff.SERVER_PENDING_CODES", 1
    )
    handoff(conn, **payload(), actor_id=6)
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_capacity"):
        handoff(
            conn, **payload(device_code_sha256="a" * 64, user_code="Z9Q2"), actor_id=6
        )


def test_disabled_service_cannot_handoff(conn):
    conn.execute("UPDATE actors SET status='disabled' WHERE id=6")
    with pytest.raises(codes.MachineAuthorizationError, match="permission_denied"):
        handoff(conn, **payload(), actor_id=6)


def test_identical_pending_handoff_replay_returns_the_existing_row(conn):
    body = payload()
    first = handoff(conn, **body, actor_id=6)
    assert handoff(conn, **body, actor_id=6) == first
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == 1
    )
    decisions.resolve(conn, code=body["user_code"], actor_id=1, action="approve")
    with pytest.raises(codes.MachineAuthorizationError, match="device_code_taken"):
        handoff(conn, **body, actor_id=6)


@pytest.mark.parametrize(
    "change", [{"org_id": 1}, {"machine_name": "Changed"}, {"platform": "Other"}]
)
def test_digest_replay_cannot_change_org_or_machine_facts(conn, change):
    body = payload()
    handoff(conn, **body, actor_id=6)
    with pytest.raises(codes.MachineAuthorizationError, match="device_code_taken"):
        handoff(conn, **{**body, **change}, actor_id=6)


def test_expiry_cannot_exceed_engine_code_ttl(conn):
    with pytest.raises(
        codes.MachineAuthorizationError, match="authorization_expiry_invalid"
    ):
        handoff(
            conn,
            **payload(expires_at=format_instant(utc_now() + timedelta(hours=1))),
            actor_id=6,
        )


def test_handoff_expires_old_rows_and_has_no_public_client_budget(conn):
    handoff(conn, **payload(), actor_id=6)
    conn.execute(
        "UPDATE machine_authorization_codes SET expires_at='2000-01-01T00:00:00Z'"
    )
    for number in range(codes.CLIENT_PENDING_CODES + 1):
        # Four characters in the shared alphabet, unique across this small set.
        code = "K7F" + "23456789A"[number]
        handoff(
            conn,
            **payload(
                device_code_sha256=hashlib.sha256(str(number).encode()).hexdigest(),
                user_code=code,
            ),
            actor_id=6,
        )
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == codes.CLIENT_PENDING_CODES + 1
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM machine_authorization_codes WHERE client_key IS NOT NULL"
        ).fetchone()[0]
        == 0
    )
