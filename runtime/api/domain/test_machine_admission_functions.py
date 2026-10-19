"""Organization-scoped machine requests, viewer identity, and serving mode."""

from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from runtime.api.cli.test_yoke_transport_function_version_skew import (
    _dispatch_over_https,
)
from runtime.api.domain.test_machine_authorization_codes import (
    conn as _conn_fixture,
    pending as start,
)
from yoke_cli.transport.function_version_skew import SKEW_ERROR_CODE
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.function_serving_floors import FUNCTION_MINIMUM_SERVING_VERSIONS
from yoke_contracts.registered_reads import READ_FUNCTION_IDS
from yoke_contracts.server_mode import SERVER_MODE_ENV
from yoke_contracts.timestamps import format_instant
from yoke_core.domain import machine_authorization_decisions as decisions
from yoke_core.domain import universe_serving_mode as modes
from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID
from yoke_core.domain.function_authz_types import ACTOR_SESSION, AuthzSpec
from yoke_core.domain.handlers import _register_inbox, machine_authorization as handler
from yoke_core.domain.machine_authorization_codes import MachineAuthorizationError

conn = _conn_fixture
FUNCTION_ID = "machine_authorization.pending"
VIEWER = {"actor_id": 1, "name": "Pat"}


def _call(conn, monkeypatch, *, payload=None, actor_id="1"):
    monkeypatch.setattr(handler.db_helpers, "connect", lambda: nullcontext(conn))
    return handler.handle_pending(
        FunctionCallRequest(
            function=FUNCTION_ID,
            actor=ActorContext(actor_id=actor_id, session_id=""),
            target=TargetRef(kind="global"),
            payload=payload or {},
        )
    )


def test_pending_is_scoped_and_returns_only_safe_fields(conn, monkeypatch):
    conn.execute("UPDATE actors SET name='Pat' WHERE id=1")
    conn.execute("UPDATE actors SET name='Sam' WHERE id=5")
    conn.execute(
        "INSERT INTO organizations (id,slug,name,created_at) "
        "VALUES (2, 'other', 'Other', 'now')"
    )
    codes = [start(conn, client_key=f"client-{i}")["user_code"] for i in range(7)]
    conn.execute(
        "UPDATE machine_authorization_codes SET org_id=2 WHERE user_code=?", (codes[2],)
    )
    now = decisions._now()
    conn.execute(
        "UPDATE machine_authorization_codes SET expires_at=? WHERE user_code=?",
        (format_instant(now), codes[3]),
    )
    conn.execute(
        "UPDATE machine_authorization_codes SET consumed_at=? WHERE user_code=?",
        (format_instant(now), codes[4]),
    )
    for code, decision in zip(codes[5:], ("approve", "deny")):
        conn.execute(
            "UPDATE machine_authorization_codes SET decision=? WHERE user_code=?",
            (decision, code),
        )
    conn.execute(
        "UPDATE machine_authorization_codes SET actor_id=5 WHERE user_code=?",
        (codes[1],),
    )
    monkeypatch.setattr(decisions, "_now", lambda: now)
    result = _call(conn, monkeypatch)
    assert result.primary_success
    body = result.result_payload
    assert set(body) == {"viewer", "requests", "mode"}
    assert body["viewer"] == VIEWER
    assert body["mode"] == modes.universe_mode()
    rows = {row["code"]: row for row in body["requests"]}
    assert set(rows) == set(codes[:2])
    assert rows[codes[0]]["requested_by"] is None
    assert rows[codes[1]]["requested_by"] == {"actor_id": 5, "name": "Sam"}
    for row in rows.values():
        assert set(row) == {
            "code",
            "machine",
            "machine_id",
            "platform",
            "expires_at",
            "requested_by",
            "state",
        }
        assert row["state"] == "pending"
        assert row["machine"] == "Pat's laptop"
        assert row["platform"] == "macOS"
    assert (
        handler.AuthorizationPendingResponse.model_validate(body).model_dump() == body
    )


@pytest.mark.parametrize(
    "actor_id,disabled,error",
    [(2, False, "organization_membership_required"), (1, True, "actor_disabled")],
)
def test_pending_refuses_nonmembers_and_disabled_actors(
    conn, monkeypatch, actor_id, disabled, error
):
    start(conn)
    if disabled:
        conn.execute("UPDATE actors SET status='disabled' WHERE id=?", (actor_id,))
    outcome = _call(conn, monkeypatch, actor_id=str(actor_id))
    assert not outcome.primary_success
    assert outcome.error.code == error


def test_pending_requires_an_actor_and_an_empty_payload(conn, monkeypatch):
    assert _call(conn, monkeypatch, actor_id=None).error.code == "actor_required"
    assert (
        _call(conn, monkeypatch, payload={"org_id": 2}).error.code
        == "authorization_refused"
    )
    with pytest.raises(ValidationError):
        handler.AuthorizationPendingRequest.model_validate({"org_id": 2})


def test_pending_empty_list_still_names_viewer(conn):
    conn.execute("UPDATE actors SET name='Pat' WHERE id=1")
    result = decisions.pending(conn, actor_id=1)
    assert result["viewer"] == VIEWER
    assert result["requests"] == []


@pytest.mark.parametrize(
    "decision,expired,consumed,state",
    [
        (None, False, False, "pending"),
        ("approve", False, False, "approved"),
        ("deny", False, False, "denied"),
        ("approve", True, False, "expired"),
        ("approve", True, True, "consumed"),
    ],
)
def test_inspect_names_viewer_binder_and_current_state(
    conn, monkeypatch, decision, expired, consumed, state
):
    conn.execute("UPDATE actors SET name='Pat' WHERE id=1")
    code = start(conn)["user_code"]
    now = decisions._now()
    monkeypatch.setattr(decisions, "_now", lambda: now)
    conn.execute(
        "UPDATE machine_authorization_codes SET actor_id=?,decision=?,expires_at=?,consumed_at=?",
        (
            1 if decision else None,
            decision,
            format_instant(now if expired else now + timedelta(minutes=1)),
            format_instant(now) if consumed else None,
        ),
    )
    result = decisions.inspect(conn, code=code, actor_id=1)
    assert result["viewer"] == VIEWER
    assert result["requested_by"] == (VIEWER if decision else None)
    assert result["state"] == state
    assert result["decision"] == decision


def test_inspect_preserves_bound_actor_refusal(conn):
    code = start(conn)["user_code"]
    conn.execute("UPDATE machine_authorization_codes SET actor_id=5")
    with pytest.raises(MachineAuthorizationError, match="authorization_owner_mismatch"):
        decisions.inspect(conn, code=code, actor_id=1)


@pytest.mark.parametrize("hosted", [False, True])
@pytest.mark.parametrize("env", [None, "", " ", "self-host", " self-host ", "unknown"])
def test_mode_owner_and_pending_agree(conn, monkeypatch, hosted, env):
    monkeypatch.setattr(
        modes.universe_startup_lock, "hosted_tenant_container_process", lambda: hosted
    )
    if env is None:
        monkeypatch.delenv(SERVER_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(SERVER_MODE_ENV, env)
    expected = (
        "hosted"
        if hosted
        else "self-host"
        if env and env.strip() == "self-host"
        else "local"
    )
    assert modes.universe_mode() == expected
    assert decisions.pending(conn, actor_id=1)["mode"] == expected


def test_pending_registration_declares_read_scope_floor_and_live_adapter():
    rows = {}

    def register(function_id, *args, **metadata):
        rows[function_id] = (args, metadata)

    _register_inbox.register(SimpleNamespace(register=register))
    args, metadata = rows[FUNCTION_ID]
    assert args == (
        handler.handle_pending,
        handler.AuthorizationPendingRequest,
        handler.AuthorizationPendingResponse,
    )
    assert metadata == {
        "stability": "stable",
        "owner_module": handler.__name__,
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": ["verified_actor", "org_membership"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
        "minimum_serving_version": "next-release",
    }
    assert PRODUCT_AUTHZ_BY_ID[FUNCTION_ID] == AuthzSpec(ACTOR_SESSION, None)
    assert FUNCTION_ID in READ_FUNCTION_IDS
    assert FUNCTION_MINIMUM_SERVING_VERSIONS[FUNCTION_ID] == "next-release"
    for function_id in ("machine_authorization.get", "machine_authorization.resolve"):
        original = rows[function_id][1]
        assert original["adapter_status"] == "live"
        assert original["guardrails"] == [
            "verified_actor",
            "own_machine_approval",
            "org_membership",
        ]


def test_dispatcher_names_floor_when_server_lacks_pending(monkeypatch):
    response = _dispatch_over_https(
        monkeypatch,
        function_id=FUNCTION_ID,
        server_version="1.0.0",
        client_version="2.0.0",
    )
    assert not response.success
    assert response.error.code == SKEW_ERROR_CODE
    assert "next-release" in response.error.message
    assert "minimum serving version" in response.error.message.lower()
