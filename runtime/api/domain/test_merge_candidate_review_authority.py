"""A candidate review is answered by somebody other than the worker.

Authority for every other decision kind is the actor's role. That is not
enough here: on a workstation every agent carries the operator's own actor,
so an actor-only rule would let the worker whose branch is waiting approve
its own candidate. These cases pin the session-bound rule that replaces it,
and the matching rule on the posture key — because turning the requirement
off is the same decision as answering it.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.steering_claim_test_support import (
    acquire_steering,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.merge_candidate_review_authority import (
    SELF_CLEARANCE_CODE,
    UNAUTHORIZED_CODE,
)
from yoke_core.domain.merge_candidate_review_gate import (
    POSTURE_KEY,
    evaluate_candidate_review,
)
from yoke_core.domain.work_claim_targets import make_item_target

HEAD = "e" * 40
WORKER_SESSION = "candidate-review-worker"
STEERING_SESSION = "candidate-review-seat"
BYSTANDER_SESSION = "candidate-review-bystander"
REVIEWER = 9301


def _item(conn) -> int:
    row = insert_item(
        conn,
        id=2880,
        workflow_id="dash",
        status="reviewing-implementation",
        workflow_posture=json.dumps({POSTURE_KEY: True}),
    )
    return int(row["id"])


def _project_id(conn, item_id: int) -> int:
    return int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )


def _human_reviewer(conn, project_id: int) -> None:
    seed_roles_and_permissions(conn)
    conn.execute(
        "INSERT INTO actors (id, kind, system_component, created_at) "
        "VALUES (%s, 'human', NULL, NOW()) ON CONFLICT DO NOTHING",
        (REVIEWER,),
    )
    grant_actor_project_role(
        conn, actor_id=REVIEWER, project_id=project_id, role_name=ROLE_OWNER
    )


def _hold_item(conn, session_id: str, item_id: int) -> None:
    target = make_item_target(item_id)
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, 'exclusive', %s, %s)",
        (session_id, target.kind, target.scope_json(), now, now),
    )
    conn.commit()


def _world(conn) -> tuple[int, int, int]:
    """One item under review, held by a worker, with a human reviewer."""
    item_id = _item(conn)
    project_id = _project_id(conn, item_id)
    _human_reviewer(conn, project_id)
    seed_session(conn, WORKER_SESSION, project_id)
    _hold_item(conn, WORKER_SESSION, item_id)
    verdict = evaluate_candidate_review(
        conn,
        item_id=item_id,
        commit_sha=HEAD,
        branch="YOK-9000",
        target="main",
        touched_files=("packages/a.py",),
        session_id=WORKER_SESSION,
    )
    assert verdict.satisfied is False
    return item_id, project_id, int(verdict.request_id)


def test_the_worker_holding_the_item_cannot_clear_its_own_candidate() -> None:
    """The defect this rule exists for: same actor, different session."""
    with test_database() as conn:
        _item_id, _project_id_, request_id = _world(conn)
        with pytest.raises(PermissionError) as caught:
            resolve_decision_request(
                conn,
                request_id,
                actor_id=REVIEWER,
                action="approve",
                note="approving my own branch",
                session_id=WORKER_SESSION,
            )
        message = str(caught.value)
        assert SELF_CLEARANCE_CODE in message
        assert "holds the item's work claim" in message
        assert "yoke claims steering list" in message


def test_the_covering_steering_seat_clears_it() -> None:
    with test_database() as conn:
        item_id, project_id, request_id = _world(conn)
        seed_session(conn, STEERING_SESSION, project_id)
        acquire_steering(conn, STEERING_SESSION, project_id)
        row = resolve_decision_request(
            conn,
            request_id,
            actor_id=REVIEWER,
            action="approve",
            note="read the diff",
            session_id=STEERING_SESSION,
        )
        assert row["status"] == "resolved"
        assert row["resolution_action"] == "approve"
        cleared = evaluate_candidate_review(
            conn,
            item_id=item_id,
            commit_sha=HEAD,
            branch="YOK-9000",
            target="main",
            session_id=WORKER_SESSION,
        )
        assert cleared.satisfied is True


def test_a_person_in_the_web_inbox_clears_it_with_no_harness_session() -> None:
    with test_database() as conn:
        _item_id, _project_id_, request_id = _world(conn)
        row = resolve_decision_request(
            conn,
            request_id,
            actor_id=REVIEWER,
            action="approve",
            note="answered in the Inbox",
            session_id="",
        )
        assert row["status"] == "resolved"
        assert row["resolution_action"] == "approve"


def test_a_session_holding_no_covering_seat_is_refused() -> None:
    """Any other agent on the machine carries the same actor too."""
    with test_database() as conn:
        _item_id, project_id, request_id = _world(conn)
        seed_session(conn, BYSTANDER_SESSION, project_id)
        with pytest.raises(PermissionError) as caught:
            resolve_decision_request(
                conn,
                request_id,
                actor_id=REVIEWER,
                action="approve",
                note="no seat here",
                session_id=BYSTANDER_SESSION,
            )
        assert UNAUTHORIZED_CODE in str(caught.value)
        assert "no live steering seat" in str(caught.value)


def test_the_worker_cannot_clear_the_posture_that_requires_the_review() -> None:
    """Removing the question is the same decision as answering it."""
    with test_database() as conn:
        item_id = _item(conn)
        project_id = _project_id(conn, item_id)
        _human_reviewer(conn, project_id)
        seed_session(conn, WORKER_SESSION, project_id)
        _hold_item(conn, WORKER_SESSION, item_id)
        with pytest.raises(PermissionError) as caught:
            amend_item_posture(
                conn,
                item_id=item_id,
                key=POSTURE_KEY,
                clear=True,
                reason="turning the gate off from inside the lane",
                actor_id=REVIEWER,
                session_id=WORKER_SESSION,
            )
        assert SELF_CLEARANCE_CODE in str(caught.value)


def test_the_covering_seat_may_clear_the_posture() -> None:
    with test_database() as conn:
        item_id = _item(conn)
        project_id = _project_id(conn, item_id)
        _human_reviewer(conn, project_id)
        seed_session(conn, WORKER_SESSION, project_id)
        _hold_item(conn, WORKER_SESSION, item_id)
        seed_session(conn, STEERING_SESSION, project_id)
        acquire_steering(conn, STEERING_SESSION, project_id)
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key=POSTURE_KEY,
            clear=True,
            reason="this item no longer needs a candidate review",
            actor_id=REVIEWER,
            session_id=STEERING_SESSION,
        )
        assert result["changed"] is True
        assert POSTURE_KEY not in result["after"]


def test_selecting_the_posture_needs_no_special_authority() -> None:
    """Tightening is always allowed; only relaxing is guarded."""
    with test_database() as conn:
        item_id = _item(conn)
        project_id = _project_id(conn, item_id)
        _human_reviewer(conn, project_id)
        seed_session(conn, WORKER_SESSION, project_id)
        _hold_item(conn, WORKER_SESSION, item_id)
        amend_item_posture(
            conn,
            item_id=item_id,
            key=POSTURE_KEY,
            clear=True,
            reason="seat removes it",
            actor_id=REVIEWER,
            session_id="",
        )
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key=POSTURE_KEY,
            value=True,
            reason="the worker may always ask to be reviewed",
            actor_id=REVIEWER,
            session_id=WORKER_SESSION,
        )
        assert result["after"][POSTURE_KEY] is True
