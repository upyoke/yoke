"""Recorded decisions, and the resolution each approval mode derives from them."""

from __future__ import annotations

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain.approval_decisions import list_decisions
from yoke_core.domain.decision_request_authority import (
    pending_requests_for_actor,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
)


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        for actor_id, label in ((2, "Ada"), (3, "Bo"), (5, "Cass")):
            value.execute(
                "INSERT INTO actor_labels "
                "(actor_id, surface, label, created_at) "
                "VALUES (?, 'display', ?, 'now')",
                (actor_id, label),
            )
        value.commit()
        yield value


def _request(conn, *, mode, roles=("owner",), actors=(3,), key="1907:done"):
    request, _ = create_decision_request(
        conn,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key=key,
        project_id=10,
        originator_actor_id=1,
        role_authorities=[RoleAuthority("project", 10, role) for role in roles],
        named_actor_ids=actors,
        approval_mode=mode,
        subject_context={
            "item_id": 1907,
            "item_ref": "YOK-1907",
            "item_title": "Approve the release",
            "from_stage": "reviewing-implementation",
            "to_stage": "done",
            "workflow_id": "issue",
            "workflow_version_id": 1,
            "branch_changes": {
                "branch": None,
                "commit_sha": None,
                "touched_files": [],
                "summary": "No implementation branch is recorded.",
            },
            "approval_source": {
                "kind": "workflow_approval_default",
                "entry": "approval_defaults.done",
            },
            "title": "Approve the release",
        },
        created_at="2026-07-26T12:00:00Z",
    )
    return request


def test_any_mode_resolves_on_the_first_approval(conn):
    request = _request(conn, mode="any")
    resolved = resolve_decision_request(
        conn, request["id"], actor_id=2, action="approve", note="looks right"
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolution_action"] == "approve"
    assert resolved["resolution_actor_id"] == 2
    assert resolved["approval_progress"]["satisfied"] == 1
    assert resolved["approval_progress"]["required"] == 1


def test_all_mode_needs_one_decision_per_checked_box(conn):
    request = _request(conn, mode="all")
    partial = resolve_decision_request(
        conn, request["id"], actor_id=2, action="approve", note="owner ok"
    )
    assert partial["status"] == "pending"
    progress = partial["approval_progress"]
    assert (progress["satisfied"], progress["required"]) == (1, 2)
    assert progress["outstanding"] == ["Bo"]
    assert progress["summary"] == (
        "1 of 2 decisions recorded · waiting on Bo"
    )

    finished = resolve_decision_request(
        conn, request["id"], actor_id=3, action="approve", note="named ok"
    )
    assert finished["status"] == "resolved"
    assert finished["resolution_action"] == "approve"
    assert finished["resolution_actor_id"] == 3
    assert finished["approval_progress"]["resolved"] is True
    assert [row["actor_id"] for row in list_decisions(conn, request["id"])] == [2, 3]


def test_any_rejection_by_a_listed_party_rejects_the_whole_request(conn):
    request = _request(conn, mode="all")
    resolve_decision_request(conn, request["id"], actor_id=2, action="approve")
    rejected = resolve_decision_request(
        conn, request["id"], actor_id=3, action="reject", note="not yet"
    )
    assert rejected["status"] == "resolved"
    assert rejected["resolution_action"] == "reject"


def test_a_role_box_is_satisfied_by_any_one_current_holder(conn):
    conn.execute("INSERT INTO actor_project_roles VALUES (4, 10, 1, 'later')")
    conn.commit()
    request = _request(conn, mode="all", roles=("owner",), actors=())
    resolved = resolve_decision_request(
        conn, request["id"], actor_id=4, action="approve"
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolution_actor_id"] == 4


def test_a_decision_is_final_for_the_person_who_made_it(conn):
    request = _request(conn, mode="all")
    resolve_decision_request(conn, request["id"], actor_id=2, action="approve")
    with pytest.raises(ValueError, match="already decided"):
        resolve_decision_request(conn, request["id"], actor_id=2, action="approve")


def test_an_approver_who_decided_sees_the_open_gate_as_done_for_them(conn):
    request = _request(conn, mode="all")
    resolve_decision_request(conn, request["id"], actor_id=2, action="approve")
    owner_row = pending_requests_for_actor(conn, 2)[0]
    named_row = pending_requests_for_actor(conn, 3)[0]
    assert owner_row["id"] == request["id"]
    assert owner_row["decided_by_you"] is True
    assert owner_row["your_decision"]["action"] == "approve"
    assert named_row["decided_by_you"] is False
    assert named_row["approval_progress"]["outstanding"] == ["Bo"]


def test_an_unauthorized_actor_records_no_decision(conn):
    request = _request(conn, mode="all")
    with pytest.raises(PermissionError, match="not authorized"):
        resolve_decision_request(conn, request["id"], actor_id=4, action="approve")
    assert list_decisions(conn, request["id"]) == []
