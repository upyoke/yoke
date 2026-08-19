"""Decision-request authority, audit, and Inbox projections."""

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
from yoke_core.domain.decision_request_contract import REQUEST_CREATED_EVENT
from yoke_core.domain.inbox_notifications import (
    addressed_actor_ids_for_event,
    mark_all_notifications_read,
    mark_notification_read,
    notification_rows,
)
from yoke_core.domain.item_block_notifications import (
    emit_item_block_state_notification,
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
            "item_ref": "YOK-1907",
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
    assert second["blocking"] is True
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
    assert [row["notification_kind"] for row in notification_rows(conn, 1)] == [
        "decision_request_resolved"
    ]
    notification = notification_rows(conn, 1)[0]
    assert notification["event"]["context"]["resolution_actor_label"] == "actor 4"
    assert [
        row[0] for row in conn.execute("SELECT event_name FROM events ORDER BY id")
    ] == ["DecisionRequestCreated", "DecisionRequestResolved"]


def test_request_lifecycle_addressing_resolves_live_authority_union(conn):
    request, _ = _transition_request(conn)
    event_context = {"request_id": request["id"]}
    assert addressed_actor_ids_for_event(
        conn,
        event_name=REQUEST_CREATED_EVENT,
        event_context=event_context,
    ) == (2, 3, 5)

    conn.execute("INSERT INTO actor_project_roles VALUES (4, 10, 2, 'later')")
    assert addressed_actor_ids_for_event(
        conn,
        event_name=REQUEST_CREATED_EVENT,
        event_context=event_context,
    ) == (2, 3, 4, 5)
    assert request["named_actor_ids"] == [3]


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


def test_strategy_review_is_nonblocking_and_changes_need_a_note(conn):
    request, created = create_decision_request(
        conn,
        kind="strategy_revision_review",
        subject_type="strategy_doc_revision",
        subject_key="10:WORKFLOW-TYPES:7",
        project_id=10,
        originator_actor_id=1,
        role_authorities=[RoleAuthority("project", 10, "owner")],
        named_actor_ids=[3],
        subject_context={"slug": "WORKFLOW-TYPES", "revision": 7},
    )
    assert created is True
    assert request["blocking"] is False
    with pytest.raises(ValueError, match="requires a note"):
        resolve_decision_request(
            conn, request["id"], actor_id=3, action="request_changes"
        )
    resolved = resolve_decision_request(
        conn,
        request["id"],
        actor_id=3,
        action="request_changes",
        note="Clarify the evidence contract.",
    )
    assert resolved["status"] == "resolved"


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


def test_notification_read_state_is_actor_scoped(conn):
    request, _ = _transition_request(conn)
    resolve_decision_request(conn, request["id"], actor_id=2, action="reject")
    row = notification_rows(conn, 1)[0]
    assert mark_notification_read(conn, 2, row["id"], "now") is False
    assert mark_notification_read(conn, 1, row["id"], "now") is True
    assert mark_notification_read(conn, 1, row["id"], "later") is False
    assert notification_rows(conn, 1) == []

    second, _ = create_decision_request(
        conn,
        kind="qa_needs_review",
        subject_type="qa_requirement",
        subject_key="44",
        project_id=10,
        originator_actor_id=1,
        role_authorities=[RoleAuthority("project", 10, "owner")],
    )
    resolve_decision_request(conn, second["id"], actor_id=2, action="waive")
    assert mark_all_notifications_read(conn, 1, "later") == 1
    conn.commit()
    assert notification_rows(conn, 1) == []


def test_item_block_state_is_addressed_to_accountable_owner(conn):
    conn.execute(
        "INSERT INTO items VALUES "
        "(44, 10, 4200, 'Blocked item', 'implementing', 'issue', 1)"
    )
    item = {
        "id": 44,
        "project_id": 10,
        "owner": "2",
        "source": "1",
        "blocked_reason": "Waiting for upstream schema",
    }
    assert (
        emit_item_block_state_notification(
            conn,
            item=item,
            blocked=True,
        )
        == 1
    )
    notification = notification_rows(conn, 2)[0]
    assert notification["event_name"] == "ItemBlocked"
    assert notification["event"]["context"]["item_ref"] == "YOK-4200"
    assert notification["event"]["context"]["reason"] == ("Waiting for upstream schema")
