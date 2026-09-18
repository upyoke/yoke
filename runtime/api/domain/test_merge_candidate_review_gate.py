"""A merge clearance answers one commit, and never the next one."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.merge_candidate_review_gate import (
    evaluate_candidate_review,
)


FIRST_HEAD = "a" * 40
SECOND_HEAD = "b" * 40
OWNER_ACTOR = 2


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        yield value


def _file_item(conn, *, posture: str) -> int:
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, project_sequence, title, status, workflow_id, "
        "workflow_version_id, workflow_posture) "
        "VALUES (3100, 10, 4400, 'Candidate lane', 'reviewing-implementation', "
        "'dash', 7, ?)",
        (posture,),
    )
    conn.commit()
    return 3100


def _evaluate(conn, item_id: int, head: str):
    return evaluate_candidate_review(
        conn,
        item_id=item_id,
        commit_sha=head,
        branch="YOK-4400",
        target="main",
        touched_files=("packages/a.py", "docs/b.md"),
        originator_actor_id=1,
    )


def test_an_item_without_the_posture_needs_no_review(conn):
    item_id = _file_item(conn, posture="{}")
    verdict = _evaluate(conn, item_id, FIRST_HEAD)
    assert verdict.required is False
    assert verdict.satisfied is True
    assert conn.execute("SELECT COUNT(*) FROM decision_requests").fetchone()[0] == 0


def test_the_first_evaluation_fails_closed_and_raises_the_review(conn):
    item_id = _file_item(conn, posture='{"merge_candidate_review": true}')
    verdict = _evaluate(conn, item_id, FIRST_HEAD)
    assert verdict.required is True
    assert verdict.satisfied is False
    assert verdict.request_status == "pending"
    row = conn.execute(
        "SELECT kind, subject_type, subject_key, subject_context "
        "FROM decision_requests"
    ).fetchone()
    assert row["kind"] == "merge_candidate_review"
    assert row["subject_type"] == "item_merge_candidate"
    assert row["subject_key"] == f"{item_id}:{FIRST_HEAD}"
    context = json.loads(row["subject_context"])
    assert context["commit_sha"] == FIRST_HEAD
    assert context["branch"] == "YOK-4400"
    assert context["target"] == "main"
    assert context["touched_files"] == ["packages/a.py", "docs/b.md"]
    assert context["item_ref"] == "YOK-4400"


def test_re_evaluating_the_same_head_reuses_the_open_review(conn):
    item_id = _file_item(conn, posture='{"merge_candidate_review": true}')
    first = _evaluate(conn, item_id, FIRST_HEAD)
    second = _evaluate(conn, item_id, FIRST_HEAD)
    assert second.request_id == first.request_id
    assert second.satisfied is False
    assert conn.execute("SELECT COUNT(*) FROM decision_requests").fetchone()[0] == 1


def test_a_cleared_head_lands(conn):
    item_id = _file_item(conn, posture='{"merge_candidate_review": true}')
    raised = _evaluate(conn, item_id, FIRST_HEAD)
    resolve_decision_request(
        conn,
        raised.request_id,
        actor_id=OWNER_ACTOR,
        action="approve",
        note="read the diff",
    )
    cleared = _evaluate(conn, item_id, FIRST_HEAD)
    assert cleared.required is True
    assert cleared.satisfied is True
    assert cleared.resolution_action == "approve"


def test_a_new_commit_after_a_clearance_is_a_new_candidate(conn):
    """The property the whole gate exists for: approval never travels."""
    item_id = _file_item(conn, posture='{"merge_candidate_review": true}')
    raised = _evaluate(conn, item_id, FIRST_HEAD)
    resolve_decision_request(
        conn,
        raised.request_id,
        actor_id=OWNER_ACTOR,
        action="approve",
        note="read the diff",
    )
    moved = _evaluate(conn, item_id, SECOND_HEAD)
    assert moved.required is True
    assert moved.satisfied is False
    assert moved.request_id != raised.request_id
    assert moved.request_status == "pending"
    # The earlier clearance is untouched history, not a revoked one.
    assert conn.execute(
        "SELECT status FROM decision_requests WHERE id = ?", (raised.request_id,)
    ).fetchone()[0] == "resolved"


def test_a_newer_head_retires_the_review_of_the_head_it_replaced(conn):
    """One open review per item, not one per abandoned attempt."""
    item_id = _file_item(conn, posture='{"merge_candidate_review": true}')
    stale = _evaluate(conn, item_id, FIRST_HEAD)
    current = _evaluate(conn, item_id, SECOND_HEAD)
    assert current.superseded_request_ids == (stale.request_id,)
    row = conn.execute(
        "SELECT status, withdrawal_reason FROM decision_requests WHERE id = ?",
        (stale.request_id,),
    ).fetchone()
    assert row["status"] == "withdrawn"
    assert SECOND_HEAD in row["withdrawal_reason"]
    assert conn.execute(
        "SELECT COUNT(*) FROM decision_requests WHERE status = 'pending'"
    ).fetchone()[0] == 1


def test_a_rejected_candidate_stays_rejected_until_a_new_commit(conn):
    item_id = _file_item(conn, posture='{"merge_candidate_review": true}')
    raised = _evaluate(conn, item_id, FIRST_HEAD)
    resolve_decision_request(
        conn,
        raised.request_id,
        actor_id=OWNER_ACTOR,
        action="reject",
        note="the migration is not idempotent",
    )
    again = _evaluate(conn, item_id, FIRST_HEAD)
    assert again.satisfied is False
    assert again.resolution_action == "reject"
    assert again.request_id == raised.request_id
    fixed = _evaluate(conn, item_id, SECOND_HEAD)
    assert fixed.request_status == "pending"
    assert fixed.request_id != raised.request_id


def test_an_abbreviated_head_is_refused_rather_than_matched(conn):
    item_id = _file_item(conn, posture='{"merge_candidate_review": true}')
    with pytest.raises(ValueError) as caught:
        _evaluate(conn, item_id, FIRST_HEAD[:12])
    assert "full 40-character" in str(caught.value)
