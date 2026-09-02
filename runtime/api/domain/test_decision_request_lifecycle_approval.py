"""Decision-request lifecycle approval gate behavior."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain.approval_gate import evaluate_lifecycle_approval
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.decision_request_subject_context import (
    APPROVAL_SOURCE_ITEM_POSTURE,
    APPROVAL_SOURCE_WORKFLOW_DEFAULT,
)


WORKFLOW_APPROVAL = {
    "kind": APPROVAL_SOURCE_WORKFLOW_DEFAULT,
    "entry": "approval_defaults.reviewing-implementation",
}
POSTURE_APPROVAL = {
    "kind": APPROVAL_SOURCE_ITEM_POSTURE,
    "entry": "workflow_posture.approval_on_done",
}


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        yield value


def test_lifecycle_gate_fails_closed_without_moving_the_item(conn):
    conn.execute(
        "INSERT INTO items VALUES "
        "(1907, 10, 4200, 'Identity shell', 'implementing', 'issue', 1)"
    )
    verdict = evaluate_lifecycle_approval(
        conn,
        item_id=1907,
        to_stage_id="reviewing-implementation",
        role_names=["owner"],
        approval_source=WORKFLOW_APPROVAL,
        originator_actor_id=1,
    )
    assert verdict.satisfied is False
    assert verdict.request_status == "pending"
    context = json.loads(
        conn.execute("SELECT subject_context FROM decision_requests").fetchone()[0]
    )
    assert context == {
        "item_id": 1907,
        "item_ref": "YOK-4200",
        "title": "YOK-4200 — approve the reviewing-implementation transition",
        "item_title": "Identity shell",
        "from_stage": "implementing",
        "to_stage": "reviewing-implementation",
        "workflow_id": "issue",
        "workflow_version_id": 1,
        "branch_changes": {
            "branch": None,
            "commit_sha": None,
            "touched_files": [],
            "summary": "No implementation branch is recorded for this transition.",
        },
        "approval_source": WORKFLOW_APPROVAL,
        "policy_summary": "issue@1 · approval_defaults.reviewing-implementation",
    }
    assert (
        conn.execute("SELECT status FROM items WHERE id=1907").fetchone()[0]
        == "implementing"
    )
    repeated = evaluate_lifecycle_approval(
        conn,
        item_id=1907,
        to_stage_id="reviewing-implementation",
        role_names=["owner"],
        approval_source=WORKFLOW_APPROVAL,
        originator_actor_id=1,
    )
    assert repeated.request_id == verdict.request_id
    resolve_decision_request(
        conn,
        verdict.request_id,
        actor_id=2,
        action="approve",
    )
    passed = evaluate_lifecycle_approval(
        conn,
        item_id=1907,
        to_stage_id="reviewing-implementation",
        role_names=["owner"],
        approval_source=WORKFLOW_APPROVAL,
        originator_actor_id=1,
    )
    assert passed.satisfied is True
    assert (
        conn.execute("SELECT status FROM items WHERE id=1907").fetchone()[0]
        == "implementing"
    )


def test_rejected_gate_creates_a_fresh_request_on_the_next_attempt(conn):
    conn.execute(
        "INSERT INTO items VALUES "
        "(1908, 10, 1908, 'Named gate', 'implementing', 'dash', 1)"
    )
    first = evaluate_lifecycle_approval(
        conn,
        item_id=1908,
        to_stage_id="done",
        named_actor_ids=[3],
        approval_source=POSTURE_APPROVAL,
        originator_actor_id=1,
    )
    resolve_decision_request(
        conn,
        first.request_id,
        actor_id=3,
        action="reject",
    )
    retried = evaluate_lifecycle_approval(
        conn,
        item_id=1908,
        to_stage_id="done",
        named_actor_ids=[3],
        approval_source=POSTURE_APPROVAL,
        originator_actor_id=1,
    )
    assert retried.satisfied is False
    assert retried.request_status == "pending"
    assert retried.request_id != first.request_id
    assert (
        conn.execute("SELECT status FROM items WHERE id=1908").fetchone()[0]
        == "implementing"
    )
