"""Scoped capture settlement wakes its owner once for independent review."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from runtime.api.domain.test_qa_capture_pending_review import (
    MEMBER,
    STAGE,
    _seed_pending,
    _submit,
)
from yoke_core.domain.deployment_qa_stage_wake import notify_item_scoped_qa_wait
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_agent_review_wake import notify_scoped_agent_review
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_settled_review import (
    SETTLED_REVIEW_WAKE_REASON,
    open_unsettled_roster,
)
from yoke_core.domain.session_explicit_wake import explicit_stopped_wake_requested
from yoke_core.domain.work_claim_targets import make_item_target

OWNER = "capture-session"
STEERING = "review-steering"


def _owner(conn, *, executor="claude-code", surface="claude-cli"):
    _project(conn)
    seed_session(conn, OWNER)
    conn.execute(
        "UPDATE harness_sessions SET mode='parked',executor=%s,"
        "executor_surface=%s,executor_version=%s WHERE session_id=%s",
        (
            executor,
            surface,
            {
                "claude-code": "2.1.238",
                "codex": "0.148.0-alpha.15",
                "cursor": "2026.08.25-3e8eec8",
            }[executor],
            OWNER,
        ),
    )
    _claim(
        conn,
        session_id=OWNER,
        target_kind="item",
        scope_json=make_item_target(MEMBER).scope_json(),
    )


@pytest.mark.parametrize(
    ("executor", "surface"),
    [
        ("claude-code", "claude-cli"),
        ("codex", "codex-cli"),
        ("cursor", "cursor-cli"),
    ],
)
def test_capture_transition_wakes_parked_owner_and_reentry_does_not_recapture(
    test_db,
    executor,
    surface,
):
    _owner(test_db, executor=executor, surface=surface)
    run_id = f"run-review-wake-{executor}"
    execution, bundle, _requirement = _seed_pending(test_db, run_id, "item")
    key = f"qa-plan-agent-review:{execution['id']}"

    assert _recipients(test_db, key) == [OWNER]
    [body] = _bodies(test_db, key)
    ref = render_item_ref(test_db, MEMBER)
    assert (
        f"yoke watch qa-plan -- --deployment-run-id {run_id} "
        f"--stage {STAGE} --member {ref} --project yoke"
    ) in body
    assert "no QA verdict exists yet" in body
    assert "--plan" not in body
    snapshot = test_db.execute(
        "SELECT routing_snapshot FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.idempotency_key=%s",
        (key,),
    ).fetchone()[0]
    assert explicit_stopped_wake_requested(snapshot)
    replay = begin_plan_review(test_db, execution)
    assert replay["bundle_id"] == bundle["bundle_id"]
    notify_scoped_agent_review(test_db, execution)
    assert _recipients(test_db, key) == [OWNER]
    assert test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == 1


def test_prior_stage_wait_does_not_absorb_review_notice(test_db, monkeypatch):
    _owner(test_db)

    def notify_after_stage_wait(conn, execution):
        notify_item_scoped_qa_wait(
            conn,
            run_id=execution["deployment_run_id"],
            stage_name=STAGE,
            item_id=MEMBER,
            project_id=1,
            reasons="needs capture",
            names_cases=True,
        )
        return notify_scoped_agent_review(conn, execution)

    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_agent_review_wake.notify_scoped_agent_review",
        notify_after_stage_wait,
    )
    execution, _bundle, _requirement = _seed_pending(
        test_db, "run-review-distinct", "item"
    )

    assert _recipients(test_db, f"qa-plan-agent-review:{execution['id']}") == [OWNER]
    assert test_db.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 2


@pytest.mark.parametrize("gone", ["missing", "terminated"])
def test_gone_owner_reaches_steering_with_normal_restaffing_recovery(test_db, gone):
    _project(test_db)
    if gone == "terminated":
        seed_session(test_db, OWNER)
        test_db.execute(
            "UPDATE harness_sessions SET terminated_at=last_heartbeat "
            "WHERE session_id=%s",
            (OWNER,),
        )
    seed_session(test_db, STEERING)
    _claim(
        test_db,
        session_id=STEERING,
        target_kind="steering",
        scope_json='{"project_id":1}',
    )
    execution, _bundle, _requirement = _seed_pending(
        test_db, f"run-review-{gone}", "item"
    )

    key = f"qa-plan-agent-review:{execution['id']}"
    assert _recipients(test_db, key) == [STEERING]
    [body] = _bodies(test_db, key)
    assert f"Owning session {OWNER} is gone" in body
    assert "idle/gone-holder starvation and restaffing" in body
    assert "--stage" in body and "--member" in body


def test_delegated_capture_wakes_execution_owner_rather_than_another_holder(test_db):
    _owner(test_db)
    seed_session(test_db, "different-holder")
    test_db.execute(
        "UPDATE work_claims SET session_id='different-holder' WHERE session_id=%s",
        (OWNER,),
    )
    execution, _bundle, _requirement = _seed_pending(
        test_db, "run-review-delegated", "item"
    )
    assert _recipients(test_db, f"qa-plan-agent-review:{execution['id']}") == [OWNER]


def test_run_scoped_review_does_not_emit_an_item_notice(test_db):
    _owner(test_db)
    _seed_pending(test_db, "run-review-run-scope", "run")
    assert test_db.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0


def test_capture_and_notice_roll_back_together_on_notice_failure(test_db, monkeypatch):
    _owner(test_db)

    def fail_notice(*args, **kwargs):
        raise RuntimeError("notice unavailable")

    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_agent_review_wake.push_notice", fail_notice
    )
    with pytest.raises(RuntimeError, match="notice unavailable"):
        _seed_pending(test_db, "run-review-rollback", "item")
    test_db.rollback()
    assert (
        test_db.execute("SELECT state FROM qa_plan_executions").fetchone()[0]
        == "active"
    )
    assert (
        test_db.execute("SELECT COUNT(*) FROM qa_plan_review_bundles").fetchone()[0]
        == 0
    )


def _reenter(conn, execution):
    return begin_plan_execution(
        conn,
        deployment_run_id=execution["deployment_run_id"],
        deployment_stage=execution["deployment_stage"],
        deployment_member_item_id=execution["deployment_member_item_id"],
        actor_id="2",
        session_id=OWNER,
    )


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_pending_reentry_reprints_the_same_bundle(test_db):
    _owner(test_db)
    execution, bundle, _requirement = _seed_pending(
        test_db, "run-review-pending-reentry", "item"
    )
    runs = _count(test_db, "qa_runs")
    executions = _count(test_db, "qa_plan_executions")

    replay = _reenter(test_db, execution)

    assert replay["id"] == execution["id"]
    assert replay["state"] == "awaiting_agent_review"
    assert "settled_review" not in replay
    review = begin_plan_review(test_db, replay)
    assert review["bundle_id"] == bundle["bundle_id"]
    assert review["state"] == "pending"
    assert _count(test_db, "qa_runs") == runs
    assert _count(test_db, "qa_plan_executions") == executions


def test_settled_reentry_reprints_verdict_without_a_new_capture(test_db):
    _owner(test_db)
    execution, bundle, requirement_id = _seed_pending(
        test_db, "run-review-settled-reentry", "item"
    )
    _submit(test_db, execution, bundle, requirement_id, "fail")
    runs = _count(test_db, "qa_runs")
    executions = _count(test_db, "qa_plan_executions")

    replay = _reenter(test_db, execution)

    assert replay["id"] == execution["id"]
    assert replay["settled_review"] == [
        verdict
        for verdict in replay["settled_review"]
        if verdict["requirement_id"] == requirement_id
    ]
    assert replay["settled_review"][0]["verdict"] == "fail"
    assert _count(test_db, "qa_runs") == runs
    assert _count(test_db, "qa_plan_executions") == executions


def test_recorded_verdict_cancels_the_review_wake(test_db):
    _owner(test_db)
    execution, bundle, requirement_id = _seed_pending(
        test_db, "run-review-cancel", "item"
    )
    key = f"qa-plan-agent-review:{execution['id']}"
    _submit(test_db, execution, bundle, requirement_id, "fail")

    row = test_db.execute(
        "SELECT m.cancellation_reason, r.state FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key=%s",
        (key,),
    ).fetchone()
    assert str(row["cancellation_reason"]).startswith(SETTLED_REVIEW_WAKE_REASON)
    assert row["state"] == "cancelled"
    assert notify_scoped_agent_review(test_db, execution) == ""
    assert _count(test_db, "session_messages") == 1


def test_delivery_cancels_a_review_wake_whose_verdict_landed(test_db, monkeypatch):
    _owner(test_db)
    execution, bundle, requirement_id = _seed_pending(
        test_db, "run-review-delivery-cancel", "item"
    )
    key = f"qa-plan-agent-review:{execution['id']}"
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_settled_review.withdraw_settled_agent_review_wakes",
        lambda *args, **kwargs: 0,
    )
    _submit(test_db, execution, bundle, requirement_id, "fail")
    assert (
        test_db.execute(
            "SELECT cancellation_reason FROM session_messages WHERE idempotency_key=%s",
            (key,),
        ).fetchone()[0]
        is None
    )
    monkeypatch.undo()
    from yoke_core.domain.session_message_delivery import expire_due_recipients

    assert expire_due_recipients(test_db) >= 0
    reason = test_db.execute(
        "SELECT cancellation_reason FROM session_messages WHERE idempotency_key=%s",
        (key,),
    ).fetchone()[0]
    assert str(reason).startswith(SETTLED_REVIEW_WAKE_REASON)


def test_unsettled_requirement_remains_eligible_to_capture(test_db):
    _owner(test_db)
    execution, bundle, requirement_id = _seed_pending(
        test_db, "run-review-partial", "item"
    )
    _submit(test_db, execution, bundle, requirement_id, "fail")
    roster = [dict(row) for row in execution["roster"]]
    extra = dict(roster[0])
    extra["requirement_id"] = requirement_id + 1
    extra["ordinal"] = 1
    roster.append(extra)

    reprint, kept = open_unsettled_roster(
        test_db,
        roster,
        item_id=None,
        transition_id=None,
        deployment_run_id=execution["deployment_run_id"],
        deployment_stage=execution["deployment_stage"],
        deployment_member_item_id=execution["deployment_member_item_id"],
    )

    assert reprint is None
    assert [int(row["requirement_id"]) for row in kept] == [requirement_id + 1]
