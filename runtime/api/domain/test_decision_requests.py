"""Decision-request authority, audit, and Inbox reads."""

from __future__ import annotations

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    decision_request_authority_actor_ids,
    list_subject_requests,
    pending_requests_for_actor,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
    withdraw_decision_request,
)


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        yield value


def _transition_request(conn):
    return create_decision_request(
        conn,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key="1907:reviewing-implementation",
        project_id=10,
        originator_actor_id=1,
        role_authorities=[
            RoleAuthority("project", 10, "owner"),
            RoleAuthority("project", 10, "operator"),
            RoleAuthority("org", 1, "admin"),
        ],
        named_actor_ids=[3],
        subject_context={
            "item_id": 1907,
            "public_ref": "YOK-1907",
            "from_stage": "reviewing-implementation",
            "transition": "reviewing-implementation",
            "workflow_id": "issue",
            "workflow_version_id": 1,
            "title": "Fold GitHub identity into app shell",
        },
        created_at="2026-07-26T12:00:00Z",
    )


def test_create_is_open_subject_idempotent_and_audited(conn):
    first, created = _transition_request(conn)
    second, created_again = _transition_request(conn)
    assert created is True
    assert created_again is False
    assert second["id"] == first["id"]
    assert second["actions"] == ["approve", "reject"]
    assert conn.execute("SELECT COUNT(*) FROM decision_requests").fetchone()[0] == 1
    events = conn.execute("SELECT event_name FROM events ORDER BY id").fetchall()
    assert [row[0] for row in events] == ["DecisionRequestCreated"]


@pytest.mark.parametrize("subject_key", ("1907", "1907:", ":done", "x:done:a"))
def test_lifecycle_request_rejects_malformed_subject_keys(conn, subject_key):
    with pytest.raises(ValueError, match="<item_id>:<stage_id>"):
        create_decision_request(
            conn,
            kind="lifecycle_transition_approval",
            subject_type="item_transition",
            subject_key=subject_key,
            project_id=10,
            role_authorities=[RoleAuthority("project", 10, "owner")],
        )


def test_live_role_union_named_priority_and_authorized_resolution(conn):
    request, _ = _transition_request(conn)
    owner = pending_requests_for_actor(conn, 2)
    named = pending_requests_for_actor(conn, 3)
    admin = pending_requests_for_actor(conn, 5)
    assert owner[0]["authority_reason"] == "project owner"
    assert named[0]["asked_of_you"] is True
    assert admin[0]["authority_reason"] == "org admin"
    assert pending_requests_for_actor(conn, 4) == []
    assert decision_request_authority_actor_ids(conn, request["id"]) == (2, 3, 5)

    conn.execute("INSERT INTO actor_project_roles VALUES (4, 10, 2, 'later')")
    assert decision_request_authority_actor_ids(conn, request["id"]) == (2, 3, 4, 5)
    assert pending_requests_for_actor(conn, 4)[0]["authority_reason"] == (
        "project operator"
    )
    resolved = resolve_decision_request(
        conn,
        request["id"],
        actor_id=4,
        action="approve",
        note="Evidence checked",
        resolved_at="2026-07-26T12:05:00Z",
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolution_action"] == "approve"
    assert pending_requests_for_actor(conn, 2) == []
    assert [
        row[0] for row in conn.execute("SELECT event_name FROM events ORDER BY id")
    ] == ["DecisionRequestCreated", "DecisionRequestResolved"]


def test_unauthorized_resolution_refuses_without_state_change(conn):
    request, _ = _transition_request(conn)
    with pytest.raises(PermissionError, match="not authorized"):
        resolve_decision_request(conn, request["id"], actor_id=4, action="approve")
    assert (
        list_subject_requests(conn, "item_transition", "1907:reviewing-implementation")[
            0
        ]["status"]
        == "pending"
    )


def test_retired_review_kind_is_outside_the_closed_vocabulary(conn):
    with pytest.raises(ValueError, match="unknown decision request kind"):
        create_decision_request(
            conn,
            kind="strategy_revision_review",
            subject_type="strategy_doc_revision",
            subject_key="10:WORKFLOW-TYPES:7",
            project_id=10,
            role_authorities=[RoleAuthority("project", 10, "owner")],
        )


def test_withdrawal_is_explicit_and_audited(conn):
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, title, status, workflow_id, workflow_version_id) "
        "VALUES (1907, 10, 'Item', 'reviewing-implementation', 'issue', 1)"
    )
    request, _ = _transition_request(conn)
    conn.execute("UPDATE items SET status = 'cancelled' WHERE id = 1907")
    withdrawn = withdraw_decision_request(
        conn,
        request["id"],
        reason="item cancelled",
        actor_id=2,
        withdrawn_at="2026-07-26T13:00:00Z",
    )
    assert withdrawn["status"] == "withdrawn"
    assert withdrawn["withdrawal_reason"] == "item cancelled"
    assert [
        row[0] for row in conn.execute("SELECT event_name FROM events ORDER BY id")
    ] == ["DecisionRequestCreated", "DecisionRequestWithdrawn"]
