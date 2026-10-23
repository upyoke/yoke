"""Approving a member's done gate retries that member's own close-out.

The member's item QA is accepted on an executing run and it owes no
post-deploy check, but its done transition waits on a human approval. The
approval answers with no driver and no owner wake; the decision's own notice
re-runs the ordinary close-out, so the member reaches done, the approval is
consumed and its claim is released — while the run stays at its stage.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.domain.test_independent_member_delivery_close_out import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)
from runtime.api.domain.test_no_obligation_member_close_out import _no_obligation
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_request_schema import create_decision_request_tables
from yoke_core.domain.work_claim_target_sql import scope_int_sql

RUN_ID = "run-done-approval"


def _approval_members(conn: Any, *members: int) -> None:
    """Each member owes a done approval and no post-deploy check."""
    create_decision_request_tables(conn)
    _seed_final_run(conn, RUN_ID, shared_qa=False)
    for item_id in members:
        conn.execute(
            "UPDATE items SET workflow_posture=%s WHERE id=%s",
            (json.dumps({"approval_on_done": True}), item_id),
        )
        _no_obligation(conn, item_id, reason="nothing observable once deployed")
    conn.commit()
    for item_id in members:
        _settle(conn, run_id=RUN_ID, stage="item-qa", member=item_id)


def _done_request(conn: Any, item_id: int) -> Any:
    return conn.execute(
        "SELECT id,status,consumed_at FROM decision_requests "
        "WHERE kind='lifecycle_transition_approval' AND subject_key=%s "
        "ORDER BY id DESC LIMIT 1",
        (f"{item_id}:done",),
    ).fetchone()


def _owner(conn: Any) -> int:
    return int(
        conn.execute(
            "SELECT apr.actor_id FROM actor_project_roles apr "
            "JOIN roles r ON r.id=apr.role_id JOIN actors a ON a.id=apr.actor_id "
            "WHERE apr.project_id=1 AND r.name='owner' AND a.kind='human' "
            "ORDER BY apr.actor_id LIMIT 1"
        ).fetchone()[0]
    )


def _live_claim(conn: Any, item_id: int) -> Any:
    item_scope = scope_int_sql(conn, "scope", "item_id")
    return conn.execute(
        "SELECT id FROM work_claims WHERE target_kind='item' "
        f"AND released_at IS NULL AND {item_scope}=%s",
        (item_id,),
    ).fetchone()


def _run_stage(conn: Any) -> tuple[str, str]:
    row = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s", (RUN_ID,)
    ).fetchone()
    return str(row["status"]), str(row["current_stage"])


def test_approving_the_done_gate_closes_the_member(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _approval_members(test_db, MEMBER_A)
    request = _done_request(test_db, MEMBER_A)
    assert _status(test_db, MEMBER_A) == "release"
    assert request is not None and request["status"] == "pending"

    resolve_decision_request(
        test_db, int(request["id"]), actor_id=_owner(test_db), action="approve"
    )

    assert _status(test_db, MEMBER_A) == "done"
    assert _done_request(test_db, MEMBER_A)["consumed_at"] is not None
    assert _live_claim(test_db, MEMBER_A) is None
    assert _status(test_db, MEMBER_B) == "release"
    assert _run_stage(test_db) == ("executing", "item-qa")


def test_rejecting_the_done_gate_leaves_the_member_held(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _approval_members(test_db, MEMBER_A)
    request = _done_request(test_db, MEMBER_A)

    resolve_decision_request(
        test_db, int(request["id"]), actor_id=_owner(test_db), action="reject"
    )

    assert _status(test_db, MEMBER_A) == "release"
    assert _live_claim(test_db, MEMBER_A) is not None


def test_a_sibling_open_approval_does_not_hold_the_member(
    test_db, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _approval_members(test_db, MEMBER_A, MEMBER_B)
    request = _done_request(test_db, MEMBER_A)

    resolve_decision_request(
        test_db, int(request["id"]), actor_id=_owner(test_db), action="approve"
    )

    assert _status(test_db, MEMBER_A) == "done"
    assert _status(test_db, MEMBER_B) == "release"
    assert _done_request(test_db, MEMBER_B)["status"] == "pending"
    assert _live_claim(test_db, MEMBER_B) is not None
