"""Selecting and clearing the merge-candidate-review posture on a live item.

Runs against Postgres because both halves are storage facts: the request
table's kind CHECK has to admit the new kind, and the guard reads the open
requests a clearing amendment would strand.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError
from yoke_core.domain.merge_candidate_review_gate import (
    POSTURE_KEY,
    evaluate_candidate_review,
)

HEAD = "d" * 40
REVIEWER = 9201


def _dash(conn, *, item_id: int, posture: dict) -> int:
    row = insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status="implementing",
        workflow_posture=json.dumps(posture),
    )
    return int(row["id"])


def _project_id(conn, item_id: int) -> int:
    return int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )


def _ensure_human_owner(conn, project_id: int) -> None:
    seed_roles_and_permissions(conn)
    conn.execute(
        "INSERT INTO actors (id, kind, system_component, created_at) "
        "VALUES (%s, 'human', NULL, NOW()) ON CONFLICT DO NOTHING",
        (REVIEWER,),
    )
    grant_actor_project_role(
        conn,
        actor_id=REVIEWER,
        project_id=project_id,
        role_name=ROLE_OWNER,
    )


def _raise_review(conn, item_id: int, head: str = HEAD):
    return evaluate_candidate_review(
        conn,
        item_id=item_id,
        commit_sha=head,
        branch="YOK-9000",
        target="main",
        touched_files=("packages/a.py",),
    )


def test_selecting_the_posture_accepts_a_human_reviewing_roster() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2860, posture={})
        _ensure_human_owner(conn, _project_id(conn, item_id))
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key=POSTURE_KEY,
            value=True,
            reason="steering reviews this candidate before it lands",
        )
        assert result["changed"] is True
        assert result["after"][POSTURE_KEY] is True


def test_selecting_the_posture_refuses_a_project_with_nobody_to_clear() -> None:
    """A landing gate nobody can open is a refusal with no recovery."""
    with test_database() as conn:
        item_id = _dash(conn, item_id=2861, posture={})
        project_id = _project_id(conn, item_id)
        conn.execute(
            "UPDATE actors SET kind = 'system' WHERE id IN ("
            "SELECT apr.actor_id FROM actor_project_roles apr "
            "JOIN roles r ON r.id = apr.role_id "
            "WHERE apr.project_id = %s AND r.name IN ('owner', 'operator'))",
            (project_id,),
        )
        conn.commit()
        with pytest.raises(ItemPostureAmendError, match="owner or operator"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key=POSTURE_KEY,
                value=True,
                reason="nobody human can clear a candidate here",
            )


def test_a_live_universe_stores_the_candidate_review_request() -> None:
    """The kind CHECK has to admit it, not only the Python vocabulary."""
    with test_database() as conn:
        item_id = _dash(conn, item_id=2862, posture={POSTURE_KEY: True})
        _ensure_human_owner(conn, _project_id(conn, item_id))
        verdict = _raise_review(conn, item_id)
        assert verdict.required is True
        assert verdict.satisfied is False
        stored = conn.execute(
            "SELECT kind, subject_key FROM decision_requests WHERE id = %s",
            (verdict.request_id,),
        ).fetchone()
        assert stored[0] == "merge_candidate_review"
        assert stored[1] == f"{item_id}:{HEAD}"


def test_clearing_the_posture_refuses_while_a_review_is_open() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2863, posture={POSTURE_KEY: True})
        _ensure_human_owner(conn, _project_id(conn, item_id))
        verdict = _raise_review(conn, item_id)
        with pytest.raises(ItemPostureAmendError) as caught:
            amend_item_posture(
                conn,
                item_id=item_id,
                key=POSTURE_KEY,
                clear=True,
                reason="steering changed its mind mid-review",
                # Authorized to relax the key; the open review is what
                # refuses. Session-bound authority has its own cases.
                actor_id=REVIEWER,
                session_id="",
            )
        message = str(caught.value)
        assert str(verdict.request_id) in message
        assert "yoke decision-requests resolve" in message


def test_clearing_the_posture_succeeds_once_the_review_is_settled() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2864, posture={POSTURE_KEY: True})
        _ensure_human_owner(conn, _project_id(conn, item_id))
        verdict = _raise_review(conn, item_id)
        resolve_decision_request(
            conn,
            verdict.request_id,
            actor_id=REVIEWER,
            action="approve",
            note="read the diff",
        )
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key=POSTURE_KEY,
            clear=True,
            reason="no further review needed on this item",
            actor_id=REVIEWER,
            session_id="",
        )
        assert result["changed"] is True
        assert POSTURE_KEY not in result["after"]
