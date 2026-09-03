from __future__ import annotations

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain import machine_approval_requests as approvals


def test_machine_approval_is_idempotent_org_admin_request(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        approvals,
        "list_subject_requests",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        approvals,
        "create_decision_request",
        lambda _conn, **kwargs: calls.append(kwargs) or (
            {"id": 7, "status": "pending"},
            True,
        ),
    )

    request, created = approvals.ensure_machine_approval(
        object(),
        auth_request_id="machine-request-abc",
        org_id=42,
        context={"code": "ABCD-EFGH", "machine": "test-mac"},
        originator_actor_id=9,
        session_id="session-1",
    )

    assert created is True
    assert request["id"] == 7
    assert calls[0]["kind"] == "machine_approval"
    assert calls[0]["subject_type"] == "machine_auth_request"
    assert calls[0]["subject_key"] == "machine-request-abc"
    assert calls[0]["role_authorities"][0] == approvals.RoleAuthority(
        "org", 42, "admin",
    )


def test_machine_approval_status_waits_then_returns_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        approvals,
        "list_subject_requests",
        lambda *_args: [{"status": "pending"}],
    )
    assert approvals.machine_approval_decision(
        object(), auth_request_id="machine-request-abc",
    ) is None

    monkeypatch.setattr(
        approvals,
        "list_subject_requests",
        lambda *_args: [{
            "status": "resolved",
            "resolution_action": "deny",
        }],
    )
    assert approvals.machine_approval_decision(
        object(), auth_request_id="machine-request-abc",
    ) == "deny"


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        yield value


def test_pending_lifecycle_create_and_replay_are_idempotent(conn) -> None:
    kwargs = {
        "auth_request_id": "5b234860-c927-46ab-b19a-9fb36df056aa",
        "org_id": 1,
        "state": "pending",
        "occurred_at": "2026-07-28T12:00:00Z",
        "actor_id": 5,
        "context": {"expires_at": "2026-07-28T12:10:00Z"},
        "session_id": "platform-delivery",
    }
    first, created, applied = approvals.apply_machine_approval_lifecycle(
        conn, **kwargs,
    )
    replay, created_again, applied_again = (
        approvals.apply_machine_approval_lifecycle(conn, **kwargs)
    )

    assert first is not None
    assert replay is not None
    assert replay["id"] == first["id"]
    assert (created, applied) == (True, True)
    assert (created_again, applied_again) == (False, False)
    assert conn.execute("SELECT COUNT(*) FROM decision_requests").fetchone()[0] == 1
    assert [
        row[0] for row in conn.execute("SELECT event_name FROM events ORDER BY id")
    ] == ["DecisionRequestCreated"]


@pytest.mark.parametrize("state", ("approved", "denied", "expired", "withdrawn"))
def test_pending_originator_cannot_apply_admin_terminal_state(conn, state) -> None:
    approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state="pending",
        occurred_at="2026-07-28T12:00:00Z",
        actor_id=1,
        context={"expires_at": "2026-07-28T12:10:00Z"},
    )

    with pytest.raises(PermissionError, match="not authorized"):
        approvals.apply_machine_approval_lifecycle(
            conn,
            auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
            org_id=1,
            state=state,
            occurred_at="2026-07-28T12:02:00Z",
            actor_id=1,
            context={},
            reason="terminal observation",
        )


def _pending(conn, *, org_id: int = 1):
    return approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=org_id,
        state="pending",
        occurred_at="2026-07-28T12:00:00Z",
        actor_id=5,
        context={"expires_at": "2026-07-28T12:10:00Z"},
        session_id="platform-delivery",
    )[0]


@pytest.mark.parametrize(
    ("status", "action"),
    (("approved", "approve"), ("denied", "deny")),
)
def test_terminal_first_observation_replays_without_pending_regression(
    conn, status: str, action: str,
) -> None:
    kwargs = {
        "auth_request_id": "5b234860-c927-46ab-b19a-9fb36df056aa",
        "org_id": 1,
        "state": status,
        "occurred_at": "2026-07-28T12:02:00Z",
        "actor_id": 5,
        "context": {"expires_at": "2026-07-28T12:10:00Z"},
        "session_id": "platform-delivery",
    }
    resolved, created, applied = approvals.apply_machine_approval_lifecycle(
        conn, **kwargs,
    )
    replay, replay_created, replay_applied = (
        approvals.apply_machine_approval_lifecycle(conn, **kwargs)
    )

    assert resolved is not None
    assert replay is not None
    assert resolved["resolution_action"] == replay["resolution_action"] == action
    assert (created, applied) == (True, True)
    assert (replay_created, replay_applied) == (False, False)
    with pytest.raises(ValueError, match=f"already {status}, not pending"):
        approvals.apply_machine_approval_lifecycle(
            conn,
            **{**kwargs, "state": "pending"},
        )


@pytest.mark.parametrize(
    ("status", "action"),
    (("approved", "approve"), ("denied", "deny")),
)
def test_terminal_resolution_replay_and_contradiction(
    conn, status: str, action: str,
) -> None:
    request = _pending(conn)
    resolved, _, applied = approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state=status,
        occurred_at="2026-07-28T12:02:00Z",
        actor_id=5,
        context={},
        reason="browser decision",
        session_id="platform-delivery",
    )
    replay, _, replay_applied = approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state=status,
        occurred_at="2026-07-28T12:02:00Z",
        actor_id=5,
        context={},
        reason="browser decision",
        session_id="platform-delivery",
    )

    assert resolved is not None
    assert replay is not None
    assert resolved["id"] == replay["id"] == request["id"]
    assert resolved["resolution_action"] == action
    assert applied is True
    assert replay_applied is False
    contradictory = "denied" if status == "approved" else "approved"
    with pytest.raises(ValueError, match=f"already {status}, not {contradictory}"):
        approvals.apply_machine_approval_lifecycle(
            conn,
            auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
            org_id=1,
            state=contradictory,
            occurred_at="2026-07-28T12:03:00Z",
            actor_id=5,
            context={},
        )
    events = conn.execute(
        "SELECT event_name, actor_id, created_at FROM events ORDER BY id"
    ).fetchall()
    assert [row[0] for row in events] == [
        "DecisionRequestCreated",
        "DecisionRecorded",
        "DecisionRequestResolved",
    ]
    assert [row[1] for row in events] == [5, 5, 5]
    assert events[2][2] == "2026-07-28T12:02:00Z"


@pytest.mark.parametrize("status", ("expired", "withdrawn"))
def test_terminal_withdrawal_replay_is_idempotent(conn, status: str) -> None:
    request = _pending(conn)
    reason = "authorization expired" if status == "expired" else "org changed"
    withdrawn, _, applied = approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state=status,
        occurred_at="2026-07-28T12:05:00Z",
        actor_id=5,
        context={},
        reason=reason,
    )
    replay, _, replay_applied = approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state=status,
        occurred_at="2026-07-28T12:05:00Z",
        actor_id=5,
        context={},
        reason=reason,
    )

    assert withdrawn is not None
    assert replay is not None
    assert withdrawn["id"] == replay["id"] == request["id"]
    assert withdrawn["status"] == "withdrawn"
    assert applied is True
    assert replay_applied is False
    events = conn.execute(
        "SELECT event_name, actor_id, created_at FROM events ORDER BY id"
    ).fetchall()
    assert [row[0] for row in events] == [
        "DecisionRequestCreated",
        "DecisionRequestWithdrawn",
    ]
    assert [row[1] for row in events] == [5, 5]
    assert events[1][2] == "2026-07-28T12:05:00Z"


def test_old_org_withdrawal_allows_one_new_org_request(conn) -> None:
    old_request = _pending(conn)
    approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state="withdrawn",
        occurred_at="2026-07-28T12:04:00Z",
        actor_id=5,
        context={},
        reason="authorization rebound to another organization",
    )
    conn.execute(
        "INSERT INTO organizations VALUES (2, 'next', 'Next', 'now')"
    )
    new_request, created, applied = approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=2,
        state="pending",
        occurred_at="2026-07-28T12:05:00Z",
        actor_id=5,
        context={"expires_at": "2026-07-28T12:15:00Z"},
    )

    assert new_request is not None
    assert new_request["id"] != old_request["id"]
    assert new_request["org_id"] == 2
    assert (created, applied) == (True, True)
