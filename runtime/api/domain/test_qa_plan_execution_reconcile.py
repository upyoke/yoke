"""Steering reconciliation settles QA executions their owners left behind."""

import json

import pytest

from runtime.api.domain.test_qa_abort_reset import failed_restore, operation  # noqa: F401
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import acquire, get_claim, release
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_owner
from yoke_core.domain.qa_plan_execution_reconcile import reconcile_execution
from yoke_core.domain.qa_plan_execution_state import set_plan_machine_lease
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.schema_init_tables import create_governed_tables
from yoke_core.domain.work_claim_targets import make_qa_admission_target

STEERING = "steering-session"
REASON = "owner ended before settling its walk"


def _stale(conn, execution_id):
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at='2000-01-01T00:00:00Z' WHERE id=%s",
        (execution_id,),
    )
    conn.commit()


def _reconcile(conn, execution_id):
    return reconcile_execution(
        conn,
        execution_id,
        project_id=resolve_project_id(conn, "yoke"),
        actor_id="2",
        session_id=STEERING,
        reason=REASON,
    )


def _receipt(conn, reconciliation_id):
    return query_one(
        conn,
        "SELECT * FROM qa_plan_execution_reconciliations WHERE id=%s",
        (reconciliation_id,),
    )


def test_orphan_with_released_lease_settles_without_host_contact():
    with test_database() as conn:
        execution, _requirement, _capture = captured_plan_review(conn, 4931)
        create_governed_tables(conn)
        register_session_actor(conn, execution["session_id"])
        lease = acquire(
            conn, make_qa_admission_target("reconcile-orphan"), execution["session_id"]
        )
        set_plan_machine_lease(conn, execution, lease_id=lease.id)
        release(conn, lease.id, "owner session ended")
        conn.execute(
            "UPDATE harness_sessions SET ended_at=CURRENT_TIMESTAMP WHERE session_id=%s",
            (execution["session_id"],),
        )
        _stale(conn, execution["id"])

        receipt = _reconcile(conn, execution["id"])

        settled = lock_plan_execution(conn, execution["id"])
        assert receipt["outcome"] == "aborted"
        assert receipt["released_lease_ids"] == []
        assert settled["state"] == "aborted"
        assert settled["machine_lease_id"] is None
        assert settled["session_id"] == STEERING
        assert settled["release_reason"].startswith("qa-plan-operator-reconciled")
        audit = _receipt(conn, receipt["reconciliation_id"])
        assert audit["prior_state"] == "active"
        assert audit["prior_session_id"] == execution["session_id"]
        assert audit["session_id"] == STEERING
        assert audit["reason"] == REASON
        assert json.loads(audit["released_lease_ids"]) == []
        # Aborting opened the review its completed capture owes; a later
        # reconcile only passes that review on and never reopens the walk.
        assert receipt["next_command"].startswith("yoke qa plan review-begin")
        again = _reconcile(conn, execution["id"])
        assert again["outcome"] == "review_handoff"
        assert again["review_bundle_id"] == receipt["review_bundle_id"]
        assert lock_plan_execution(conn, execution["id"])["state"] == "aborted"


def test_lost_review_passes_to_the_caller_for_review_begin():
    with test_database() as conn:
        execution, _requirement, capture = captured_plan_review(conn, 4932)
        create_governed_tables(conn)
        bundle = begin_plan_review(conn, execution)
        _stale(conn, execution["id"])

        receipt = _reconcile(conn, execution["id"])

        handed = lock_plan_execution(conn, execution["id"])
        assert receipt["outcome"] == "review_handoff"
        assert receipt["review_bundle_id"] == bundle["bundle_id"]
        assert receipt["next_command"].startswith("yoke qa plan review-begin --item ")
        assert receipt["next_command"].endswith(f"--execution-id {execution['id']}")
        assert handed["state"] == "awaiting_agent_review"
        require_plan_execution_owner(
            handed,
            conn=conn,
            item_id=4932,
            actor_id="2",
            session_id=STEERING,
            reviewing=True,
        )
        recovered = begin_plan_review(conn, handed)
        assert recovered["bundle_id"] == bundle["bundle_id"]
        assert recovered["cases"][0]["capture_run_id"] == capture
        audit = _receipt(conn, receipt["reconciliation_id"])
        assert audit["outcome"] == "review_handoff"
        assert audit["prior_state"] == "awaiting_agent_review"
        assert audit["prior_session_id"] == "review-session"


def test_live_execution_refuses_and_names_abort():
    with test_database() as conn:
        execution, _requirement, _capture = captured_plan_review(conn, 4933)
        create_governed_tables(conn)
        with pytest.raises(QaPlanExecutionStateError) as refused:
            _reconcile(conn, execution["id"])
        assert "qa_reconcile_execution_live" in str(refused.value)
        assert "yoke qa plan abort --project yoke" in str(refused.value)
        assert lock_plan_execution(conn, execution["id"])["session_id"] == (
            "review-session"
        )


def test_held_lease_refuses_with_reset_until_reset_receipt(
    test_db,
    failed_restore,
    monkeypatch,  # noqa: F811
):
    execution = failed_restore
    lease_id = int(execution["machine_lease_id"])
    _stale(test_db, execution["id"])
    with pytest.raises(QaPlanExecutionStateError) as refused:
        _reconcile(test_db, execution["id"])
    message = str(refused.value)
    assert "qa_reconcile_host_recovery_required" in message
    assert (
        "yoke test-machine reset --project yoke --machine mac-mini-lab "
        "--baseline fresh-host"
    ) in message
    assert (
        f"yoke qa plan reconcile --project yoke --execution-id {execution['id']}"
        in message
    )
    assert get_claim(test_db, lease_id).is_active
    assert lock_plan_execution(test_db, execution["id"])["state"] == "active"

    steering = ActorContext(actor_id="2", session_id=STEERING)
    monkeypatch.setattr(
        "yoke_core.domain.session_steering_authority.covering_session_seat",
        lambda *a, **kw: {"session_id": STEERING},
    )
    begun = handle_operation_begin(operation(steering))
    assert begun.primary_success, begun.error
    issued = begun.result_payload["execution"]
    submitted = handle_operation_submit(
        operation(
            steering,
            lease_id=issued["lease_id"],
            contract_digest=issued["contract_digest"],
            status="verified",
            checks=[{"name": "fresh-host", "ok": True}],
        )
    )
    assert submitted.primary_success, submitted.error

    receipt = _reconcile(test_db, execution["id"])

    assert receipt["outcome"] == "aborted"
    assert receipt["released_lease_ids"] == [lease_id]
    assert not get_claim(test_db, lease_id).is_active
    assert lock_plan_execution(test_db, execution["id"])["state"] == "aborted"


def test_dispatch_refuses_a_caller_without_a_steering_seat():
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
    from yoke_core.domain.yoke_function_registry import lookup

    register_all_handlers()
    entry = lookup("qa.plan_execution.reconcile")
    assert entry.claim_required_kind == "steering"
    with test_database() as conn:
        create_governed_tables(conn)
        register_session_actor(conn, "ordinary-session")
        conn.commit()
        refused = verify_claim(
            entry,
            FunctionCallRequest(
                function="qa.plan_execution.reconcile",
                actor=ActorContext(actor_id="2", session_id="ordinary-session"),
                target=TargetRef(kind="global", project_id="yoke"),
                payload={"execution_id": "unknown", "reason": REASON},
            ),
        )
    assert refused is not None
    assert refused.error.code == "steering_seat_required"
    assert "yoke claims steering acquire --project" in refused.error.message
