"""Hosted polling reuses domain decisions without replaying credentials."""

from contextlib import contextmanager

import pytest

from runtime.api.domain.test_machine_authorization_handoff import (  # noqa: F401
    conn as _conn_fixture,
    payload,
    registry as _registry_fixture,
    request,
)
from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    OTHER_MACHINE_ID,
)
from yoke_contracts.api.function_call import FunctionCallResponse, HandlerOutcome
from yoke_core.domain import machine_authorization_codes as codes
from yoke_core.domain import machine_authorization_decisions as decisions
from yoke_core.domain import yoke_function_dispatch_events as events
from yoke_core.domain.handlers.machine_authorization_handoff import handle_handoff_poll
from yoke_core.domain.machine_authorization_handoff import handoff
from yoke_core.domain.machine_authorization_handoff_poll import handoff_poll
from yoke_core.domain.yoke_function_dispatch_idempotency import handle_idempotency
from yoke_core.domain.yoke_function_registry import lookup


conn = _conn_fixture
registry = _registry_fixture


def poll(conn, **updates):
    return handoff_poll(
        conn,
        device_code="hosted-device-secret",
        machine_id=MACHINE_ID,
        machine_name="Laptop",
        org_id=updates.pop("org_id", 2),
        actor_id=updates.pop("actor_id", 6),
        **updates,
    )


def test_handoff_poll_tracks_existing_pending_approval_and_single_use(conn):
    handoff(conn, **payload(), actor_id=6)
    assert poll(conn) == {"state": "pending", "machine_id": MACHINE_ID}
    decisions.resolve(conn, code="K7F2", actor_id=1, action="approve")
    first = poll(conn)
    assert first["state"] == "approved"
    assert first["token"]
    assert poll(conn) == {"state": "consumed", "machine_id": MACHINE_ID}
    assert conn.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == 1


@pytest.mark.parametrize("state", ["denied", "expired"])
def test_terminal_states_come_from_domain_poll(conn, state):
    handoff(conn, **payload(), actor_id=6)
    if state == "denied":
        decisions.resolve(conn, code="K7F2", actor_id=1, action="deny")
    else:
        conn.execute(
            "UPDATE machine_authorization_codes SET expires_at='2000-01-01T00:00:00Z'"
        )
    assert poll(conn) == {"state": state, "machine_id": MACHINE_ID}
    assert conn.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == 0


def test_explicit_org_scope_holds_even_when_service_has_both_grants(conn):
    handoff(conn, **payload(), actor_id=6)
    with pytest.raises(codes.MachineAuthorizationError, match="permission_denied"):
        poll(conn, org_id=1)
    conn.execute("DELETE FROM actor_org_roles WHERE actor_id=6 AND org_id=2")
    with pytest.raises(codes.MachineAuthorizationError, match="permission_denied"):
        poll(conn)


@pytest.mark.parametrize("actor_id", [1, 5])
def test_humans_cannot_use_service_poll(conn, actor_id):
    handoff(conn, **payload(), actor_id=6)
    with pytest.raises(codes.MachineAuthorizationError, match="permission_denied"):
        poll(conn, actor_id=actor_id)


def test_unknown_and_wrong_machine_do_not_consume(conn):
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_unknown"):
        poll(conn)
    handoff(conn, **payload(), actor_id=6)
    decisions.resolve(conn, code="K7F2", actor_id=1, action="approve")
    with pytest.raises(
        codes.MachineAuthorizationError, match="machine_identity_mismatch"
    ):
        handoff_poll(
            conn,
            device_code="hosted-device-secret",
            machine_id=OTHER_MACHINE_ID,
            machine_name="Other",
            org_id=2,
            actor_id=6,
        )
    assert (
        conn.execute("SELECT consumed_at FROM machine_authorization_codes").fetchone()[
            0
        ]
        is None
    )
    assert poll(conn)["token"]


def test_failed_credential_issuance_rolls_back_then_can_retry(conn, monkeypatch):
    handoff(conn, **payload(), actor_id=6)
    decisions.resolve(conn, code="K7F2", actor_id=1, action="approve")
    real_mint = codes.register_with_credential

    def broken(*args, **kwargs):
        raise RuntimeError("credential store disconnected")

    monkeypatch.setattr(codes, "register_with_credential", broken)
    with pytest.raises(RuntimeError), conn:
        poll(conn)
    assert (
        conn.execute("SELECT consumed_at FROM machine_authorization_codes").fetchone()[
            0
        ]
        is None
    )
    monkeypatch.setattr(codes, "register_with_credential", real_mint)
    assert poll(conn)["token"]


def test_same_request_id_runs_handler_again_and_never_ledgers_or_captures_token(
    conn, registry, monkeypatch
):
    @contextmanager
    def connect():
        yield conn

    monkeypatch.setattr(
        "yoke_core.domain.handlers.machine_authorization.db_helpers.connect", connect
    )
    handoff(conn, **payload(), actor_id=6)
    decisions.resolve(conn, code="K7F2", actor_id=1, action="approve")
    req = request(
        {
            "device_code": "hosted-device-secret",
            "machine_id": MACHINE_ID,
            "machine_name": "Laptop",
            "org_id": 2,
        }
    )
    req.function = "machine_authorization.handoff_poll"
    entry = lookup(req.function)

    def forbidden(*args, **kwargs):
        pytest.fail("one-time token touched dispatcher replay or debug capture")

    assert (
        handle_idempotency(
            entry,
            req,
            identity_context=None,
            permission_key=None,
            project=None,
            authorization_scope="actor:6",
            payload_checksum="unused",
            lookup=forbidden,
        )
        is None
    )
    first = handle_handoff_poll(req)
    second = handle_handoff_poll(req)
    assert first.result_payload["authorization"]["token"]
    assert second.result_payload["authorization"]["state"] == "consumed"
    assert "token" not in second.result_payload["authorization"]
    monkeypatch.setattr(events, "record_call", forbidden)
    monkeypatch.setattr(events, "debug_detail_allowed", forbidden)
    captures = []
    monkeypatch.setattr(events, "emit_event", lambda *a, **kw: captures.append(kw))
    monkeypatch.setattr(events, "record_session_action", lambda *a, **kw: None)
    reply = FunctionCallResponse(
        success=True,
        function=req.function,
        version="v1",
        request_id=req.request_id,
        result=first.result_payload,
    )
    events.emit_called(
        req,
        entry,
        HandlerOutcome(primary_success=True),
        reply,
        10,
        "digest",
        duration_ms=1,
        authorization_scope="actor:6",
        idempotency_payload_checksum="unused",
        claim_verification={},
    )
    assert first.result_payload["authorization"]["token"] not in str(captures)


def test_poll_validation_never_echoes_device_secret(registry):
    req = request(
        {
            "device_code": "private-device-secret",
            "machine_id": MACHINE_ID,
            "machine_name": "Laptop",
            "org_id": "invalid",
        }
    )
    reply = handle_handoff_poll(req)
    assert reply.error.code == "authorization_refused"
    assert "private-device-secret" not in reply.error.message


def test_disabled_service_and_disabled_approver_cannot_receive_tokens(conn):
    handoff(conn, **payload(), actor_id=6)
    decisions.resolve(conn, code="K7F2", actor_id=1, action="approve")
    conn.execute("UPDATE actors SET status='disabled' WHERE id=6")
    with pytest.raises(codes.MachineAuthorizationError, match="permission_denied"):
        poll(conn)
    conn.execute("UPDATE actors SET status='active' WHERE id=6")
    conn.execute("UPDATE actors SET status='disabled' WHERE id=1")
    with pytest.raises(codes.MachineAuthorizationError, match="actor_disabled"):
        poll(conn)
    assert (
        conn.execute("SELECT consumed_at FROM machine_authorization_codes").fetchone()[
            0
        ]
        is None
    )
