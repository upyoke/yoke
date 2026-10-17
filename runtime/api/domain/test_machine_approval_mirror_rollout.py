"""Hosted Inbox mirrors and direct machine decisions coexist independently."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.domain.session_relay_handler_test_support import NoCloseConnection
from runtime.api.domain.test_machine_authorization_codes import (
    conn as _conn_fixture,
    pending,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.timestamps import format_instant
from yoke_core.domain import db_helpers, machine_approval_requests
from yoke_core.domain.handlers import inbox_decisions, machine_authorization

conn = _conn_fixture
AUTHORIZATION_ID = "5b234860-c927-46ab-b19a-9fb36df056aa"


def _request(function, payload, actor_id):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=str(actor_id), session_id="workbench"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_hosted_mirror_lifecycle_and_inbox_resolution_remain_live(
    conn, monkeypatch, action
):
    monkeypatch.setattr(db_helpers, "connect", lambda: NoCloseConnection(conn))
    now = datetime.now(timezone.utc)
    payload = {
        "authorization_id": AUTHORIZATION_ID,
        "state": "pending",
        "occurred_at": format_instant(now),
        "expires_at": format_instant(now + timedelta(minutes=10)),
        "code": "WXYZ-1234",
        "machine": "studio-mini",
    }
    request = _request("machine_approval.lifecycle.apply", payload, 1)
    created = machine_approval_requests.apply_machine_approval_lifecycle_request(
        request
    )
    assert created.primary_success, created.error
    row = created.result_payload["request"]
    assert created.result_payload["created"] is True
    assert (row["kind"], row["subject_type"], row["subject_key"], row["status"]) == (
        "machine_approval",
        "machine_auth_request",
        AUTHORIZATION_ID,
        "pending",
    )
    replay = machine_approval_requests.apply_machine_approval_lifecycle_request(request)
    assert replay.primary_success, replay.error
    assert replay.result_payload["created"] is False
    assert replay.result_payload["request"]["id"] == row["id"]

    resolved = inbox_decisions.handle_decision_resolve(
        _request(
            "decision_requests.resolve", {"request_id": row["id"], "action": action}, 5
        )
    )
    assert resolved.primary_success, resolved.error
    assert resolved.result_payload["request"]["status"] == "resolved"
    assert (
        machine_approval_requests.machine_approval_decision(
            conn, auth_request_id=AUTHORIZATION_ID
        )
        == action
    )
    stored = conn.execute(
        "SELECT status, resolution_action FROM decision_requests WHERE id=?",
        (row["id"],),
    ).fetchone()
    assert tuple(stored) == ("resolved", action)
    assert conn.execute("SELECT count(*) FROM decision_requests").fetchone()[0] == 1
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_self_host_resolution_writes_only_the_machine_code(conn, monkeypatch, action):
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(conn))
    authorization = pending(conn)
    assert conn.execute("SELECT count(*) FROM decision_requests").fetchone()[0] == 0
    resolved = machine_authorization.handle_resolve(
        _request(
            "machine_authorization.resolve",
            {"code": authorization["user_code"], "action": action},
            1,
        )
    )
    assert resolved.primary_success, resolved.error
    assert resolved.result_payload["authorization"]["decision"] == action
    stored = conn.execute(
        "SELECT decision, actor_id FROM machine_authorization_codes WHERE user_code=?",
        (authorization["user_code"],),
    ).fetchone()
    assert tuple(stored) == (action, 1)
    assert conn.execute("SELECT count(*) FROM decision_requests").fetchone()[0] == 0
