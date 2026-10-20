"""A walk stopped with captures awaiting review hands that review to an owner."""

from __future__ import annotations

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from runtime.api.domain.test_qa_capture_pending_review import (
    MEMBER,
    _acceptance,
    _seed_pending,
)
from yoke_core.domain.deployment_qa_stage_acceptance import STAGE_AWAITING_REVIEW
from yoke_core.domain.qa_deployment_run_settlement import (
    restore_retry_obligations,
    settle_unsuccessful_run,
)
from yoke_core.domain.qa_pending_agent_review import (
    pending_review_for_requirement,
    pending_review_requirements,
)
from yoke_core.domain.qa_plan_settled_review import (
    withdraw_settled_agent_review_wakes,
)
from yoke_core.domain.work_claim_targets import make_item_target

OWNER = "capture-session"
HOLDER = "member-holder"


def _fail_run(conn, execution):
    """The incident's stop: the run fails mid-capture, then is retried."""
    run_id = execution["deployment_run_id"]
    settle_unsuccessful_run(conn, run_id, reason=f"deployment run {run_id} failed")
    restore_retry_obligations(conn, run_id)
    conn.commit()


def _review_begin(run_id: str, execution: dict) -> str:
    return (
        f"yoke qa plan review-begin --deployment-run-id {run_id} "
        f"--execution-id {execution['id']}"
    )


def test_failed_run_abort_keeps_the_review_visible_and_wakes_its_owner(test_db):
    _project(test_db)
    seed_session(test_db, OWNER)
    run_id = "run-stopped-review-owner"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, "item")
    _fail_run(test_db, execution)

    pending = pending_review_for_requirement(test_db, requirement_id)
    assert pending is not None and pending.state == "aborted"
    assert pending.bundle_id == bundle["bundle_id"]
    assert _review_begin(run_id, execution) in pending.next_action()
    assert set(pending_review_requirements(test_db, [requirement_id])) == {
        requirement_id
    }
    acceptance = _acceptance(test_db, run_id, "item")
    assert acceptance.state == STAGE_AWAITING_REVIEW
    assert any(_review_begin(run_id, execution) in b for b in acceptance.blockers)
    assert not any("no completed scoped QA" in b for b in acceptance.blockers)

    key = f"qa-plan-agent-review:{execution['id']}:owner"
    assert _recipients(test_db, key) == [OWNER]
    [body] = _bodies(test_db, key)
    assert "stopped as aborted" in body
    assert _review_begin(run_id, execution) in body
    assert "cannot supply one" in body


def test_gone_owner_hands_the_review_to_each_waiting_member(test_db):
    _project(test_db)
    seed_session(test_db, OWNER)
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=last_heartbeat WHERE session_id=%s",
        (OWNER,),
    )
    seed_session(test_db, HOLDER)
    _claim(
        test_db,
        session_id=HOLDER,
        target_kind="item",
        scope_json=make_item_target(MEMBER).scope_json(),
    )
    run_id = "run-stopped-review-gone"
    execution, _bundle, _requirement = _seed_pending(test_db, run_id, "item")
    _fail_run(test_db, execution)

    assert _recipients(test_db, f"qa-plan-agent-review:{execution['id']}:owner") == []
    key = f"qa-plan-agent-review:{execution['id']}:{MEMBER}"
    assert _recipients(test_db, key) == [HOLDER]
    [body] = _bodies(test_db, key)
    assert f"Its capture session {OWNER} has ended" in body
    assert (
        f"yoke qa plan adopt --deployment-run-id {run_id} "
        f"--execution-id {execution['id']}"
    ) in body
    assert _review_begin(run_id, execution) in body


def test_submitted_review_withdraws_a_member_scoped_wake(test_db):
    from runtime.api.domain.test_qa_capture_pending_review import _submit

    _project(test_db)
    seed_session(test_db, HOLDER)
    _claim(
        test_db,
        session_id=HOLDER,
        target_kind="item",
        scope_json=make_item_target(MEMBER).scope_json(),
    )
    execution, bundle, requirement_id = _seed_pending(
        test_db, "run-stopped-review-withdraw", "item"
    )
    _fail_run(test_db, execution)
    _submit(test_db, execution, bundle, requirement_id, "pass")

    withdraw_settled_agent_review_wakes(test_db, execution_id=execution["id"])
    test_db.commit()
    cancelled = test_db.execute(
        "SELECT cancelled_at FROM session_messages WHERE idempotency_key=%s",
        (f"qa-plan-agent-review:{execution['id']}:{MEMBER}",),
    ).fetchone()[0]
    assert cancelled is not None
    assert pending_review_for_requirement(test_db, requirement_id) is None
