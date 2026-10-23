"""Steering reconciliation settles QA executions their owners left behind."""

import json

import pytest

from runtime.api.domain.test_qa_abort_reset import failed_restore, operation  # noqa: F401
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.coordination_claims import acquire, get_claim, release
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_owner
from yoke_core.domain.qa_plan_execution_reconcile import reconcile_execution
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


def _reconcile(conn, execution_id, session_id=STEERING):
    return reconcile_execution(
        conn,
        execution_id,
        project_id=resolve_project_id(conn, "yoke"),
        actor_id="2",
        session_id=session_id,
        reason=REASON,
    )


def _awaiting_review(conn, item_id):
    """A full captured walk whose review bundle is pending."""
    execution, requirement, capture = captured_plan_review(conn, item_id)
    create_governed_tables(conn)
    bundle = begin_plan_review(conn, execution)
    return lock_plan_execution(conn, execution["id"]), bundle, capture


def _without_artifacts(conn, bundle_id):
    """The prod shape: a mission walker that never attached its proof."""
    row = query_one(
        conn, "SELECT bundle_json FROM qa_plan_review_bundles WHERE id=%s", (bundle_id,)
    )
    payload = json.loads(row["bundle_json"])
    for case in payload["cases"]:
        case["artifacts"] = []
        case["capture_degraded_reason"] = (
            "agent_mission_docket:walker_artifacts_not_yet_attached"
        )
    conn.execute(
        "UPDATE qa_plan_review_bundles SET bundle_json=%s WHERE id=%s",
        (json.dumps(payload), bundle_id),
    )
    conn.commit()


def _receipt(conn, reconciliation_id):
    return query_one(
        conn,
        "SELECT * FROM qa_plan_execution_reconciliations WHERE id=%s",
        (reconciliation_id,),
    )


def test_orphan_without_judgeable_capture_aborts_with_no_verdict():
    with test_database() as conn:
        execution, bundle, capture = _awaiting_review(conn, 4931)
        _without_artifacts(conn, bundle["bundle_id"])
        register_session_actor(conn, execution["session_id"])
        lease = acquire(
            conn, make_qa_admission_target("reconcile-orphan"), execution["session_id"]
        )
        conn.execute(
            "UPDATE qa_plan_executions SET machine_lease_id=%s WHERE id=%s",
            (lease.id, execution["id"]),
        )
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
        assert receipt["review_bundle_id"] is None
        assert receipt["next_command"] is None
        assert settled["state"] == "aborted"
        assert settled["machine_lease_id"] is None
        assert settled["session_id"] == STEERING
        assert settled["release_reason"].startswith("qa-plan-operator-reconciled")
        closed = query_one(
            conn,
            "SELECT state,reviewer_session_id FROM qa_plan_review_bundles WHERE id=%s",
            (bundle["bundle_id"],),
        )
        assert closed["state"] == "completed"
        assert closed["reviewer_session_id"] == STEERING
        assert not query_one(
            conn,
            "SELECT 1 FROM qa_plan_review_verdicts WHERE bundle_id=%s",
            (bundle["bundle_id"],),
        )
        verdict = query_one(conn, "SELECT verdict FROM qa_runs WHERE id=%s", (capture,))
        assert verdict["verdict"] is None
        audit = _receipt(conn, receipt["reconciliation_id"])
        assert audit["prior_state"] == "awaiting_walk_review"
        assert audit["prior_session_id"] == "review-session"
        assert audit["session_id"] == STEERING
        assert audit["reason"] == REASON
        assert json.loads(audit["released_lease_ids"]) == []
        with pytest.raises(QaPlanExecutionStateError, match="qa_reconcile_already"):
            _reconcile(conn, execution["id"])


def test_lost_review_passes_to_the_caller_for_review_begin():
    with test_database() as conn:
        execution, bundle, capture = _awaiting_review(conn, 4932)
        _stale(conn, execution["id"])

        receipt = _reconcile(conn, execution["id"])

        handed = lock_plan_execution(conn, execution["id"])
        assert receipt["outcome"] == "review_handoff"
        assert receipt["review_bundle_id"] == bundle["bundle_id"]
        assert receipt["next_command"].startswith("yoke qa plan review-begin --item ")
        assert receipt["next_command"].endswith(f"--execution-id {execution['id']}")
        assert handed["state"] == "awaiting_walk_review"
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
        assert audit["prior_state"] == "awaiting_walk_review"
        assert audit["prior_session_id"] == "review-session"


def test_active_walk_is_never_settled_from_outside():
    with test_database() as conn:
        execution, _requirement, _capture = captured_plan_review(conn, 4933)
        create_governed_tables(conn)
        _stale(conn, execution["id"])
        with pytest.raises(QaPlanExecutionStateError) as refused:
            _reconcile(conn, execution["id"])
        assert "qa_reconcile_runner_driven" in str(refused.value)
        assert "yoke qa plan abort --item " in str(refused.value)
        assert lock_plan_execution(conn, execution["id"])["state"] == "active"


def test_heartbeating_review_refuses_as_live():
    with test_database() as conn:
        execution, _bundle, _capture = _awaiting_review(conn, 4934)
        with pytest.raises(QaPlanExecutionStateError) as refused:
            _reconcile(conn, execution["id"])
        assert "qa_reconcile_execution_live" in str(refused.value)
        assert lock_plan_execution(conn, execution["id"])["session_id"] == (
            "review-session"
        )


def test_held_lease_refuses_with_reset_until_reset_receipt(
    test_db,
    failed_restore,  # noqa: F811
    monkeypatch,
):
    execution = failed_restore
    lease_id = int(execution["machine_lease_id"])
    # A walk parked in a host wait has no runner driving it but keeps its host.
    test_db.execute(
        "UPDATE qa_plan_executions SET state='waiting' WHERE id=%s", (execution["id"],)
    )
    _stale(test_db, execution["id"])
    with pytest.raises(QaPlanExecutionStateError) as refused:
        _reconcile(test_db, execution["id"])
    message = str(refused.value)
    assert "qa_reconcile_host_recovery_required" in message
    assert (
        "yoke test-machine reset --project yoke --test-machine mac-mini-lab "
        "--baseline fresh-host"
    ) in message
    assert (
        f"yoke qa plan reconcile --project yoke --execution-id {execution['id']}"
        in message
    )
    assert get_claim(test_db, lease_id).is_active
    assert lock_plan_execution(test_db, execution["id"])["state"] == "waiting"

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
