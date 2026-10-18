"""Resolved item reviews reach current custody through real session messages."""

from __future__ import annotations

import pytest

from runtime.api.domain.qa_review_seed import _seed_undetermined_review
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_request_subject_effect import notify_subject_resolution
from yoke_core.domain.qa_review_requests import ensure_qa_review_request
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target


def _review(conn):
    _project(conn)
    item_id = 9788
    seeded = _seed_undetermined_review(
        conn, item_id=item_id, plan_slug="item-verdict", decider_roles=("owner",)
    )
    request, _ = ensure_qa_review_request(
        conn,
        requirement_id=seeded["requirement_id"],
        run_id=seeded["run_id"],
        originator_actor_id=seeded["originator"],
    )
    return item_id, seeded, request


def _hold(conn, item_id, session_id):
    seed_session(conn, session_id)
    _claim(
        conn,
        session_id=session_id,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )


@pytest.mark.parametrize(
    ("action", "outcome", "next_step"),
    [
        ("approve", "approved", "reviewed evidence was accepted"),
        ("reject", "rejected", "record fresh evidence"),
        ("waive", "waived", "obligation is discharged"),
    ],
)
def test_item_decision_notifies_current_holder_once(
    test_db, action, outcome, next_step
):
    item_id, seeded, request = _review(test_db)
    _hold(test_db, item_id, HOLDER_A)
    test_db.execute(
        "UPDATE work_claims SET released_at=claimed_at WHERE session_id=%s",
        (HOLDER_A,),
    )
    test_db.commit()
    _hold(test_db, item_id, HOLDER_B)
    note = "The saved state needs attention."
    result = resolve_decision_request(
        test_db, request["id"], actor_id=seeded["deciders"][0], action=action, note=note
    )
    assert result["status"] == "resolved"
    key = f"item-qa-verdict:{seeded['requirement_id']}:{action}"
    assert _recipients(test_db, key) == [HOLDER_B]
    [body] = _bodies(test_db, key)
    assert f"was {outcome}" in body
    assert next_step in body
    assert note in body
    assert f"--requirement-id {seeded['requirement_id']}" in body
    assert "deployment" not in body
    notify_subject_resolution(test_db, request, action=action, note=note)
    assert _recipients(test_db, key) == [HOLDER_B]
    assert _bodies(test_db, key) == [body]


def test_unheld_item_routes_notice_to_steering_and_retains_pending_receipt(test_db):
    _, seeded, request = _review(test_db)
    seat = "sess-review-steering"
    seed_session(test_db, seat)
    _claim(
        test_db,
        session_id=seat,
        target_kind="steering",
        scope_json=make_steering_target(1).scope_json(),
    )
    resolve_decision_request(
        test_db,
        request["id"],
        actor_id=seeded["deciders"][0],
        action="reject",
        note="Inspect the saved state.",
    )
    key = f"item-qa-verdict:{seeded['requirement_id']}:reject"
    assert _recipients(test_db, key) == [seat]
    assert "staff the item and relay this verdict" in _bodies(test_db, key)[0]
    row = test_db.execute(
        "SELECT r.state FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.idempotency_key=%s",
        (key,),
    ).fetchone()
    assert row["state"] == "pending"


def test_unaddressable_review_reports_recovery_without_reversing_verdict(
    test_db, capsys
):
    _, seeded, request = _review(test_db)
    result = resolve_decision_request(
        test_db,
        request["id"],
        actor_id=seeded["deciders"][0],
        action="reject",
        note="No worker remains.",
    )
    assert result["resolution_action"] == "reject"
    assert "nobody addressable to tell" in capsys.readouterr().out
