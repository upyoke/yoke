"""Reconciliation shapes: mission review leases, parked owners, operators."""

import pytest

from runtime.api.domain.test_qa_plan_execution_reconcile import (
    REASON,
    STEERING,
    _awaiting_review,
    _receipt,
    _reconcile,
    _stale,
    _without_artifacts,
)
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import PermissionDenied
from yoke_core.domain.coordination_claims import acquire, get_claim
from yoke_core.domain.handlers.qa_plan_execution_reconcile import _require_operator
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    lock_plan_execution,
    roster_digest,
)
from yoke_core.domain.sessions_analytics_core import SessionError
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def test_mission_review_lease_is_released_and_review_handed_over():
    with test_database() as conn:
        execution, bundle, _capture = _awaiting_review(conn, 4941)
        roster = execution["roster"]
        for case in roster:
            case["runner_id"] = "agent_mission"
        register_session_actor(conn, "review-session")
        lease = acquire(
            conn, make_qa_admission_target("reconcile-mission"), "review-session"
        )
        conn.execute(
            "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s,"
            "machine_lease_id=%s WHERE id=%s",
            (canonical(roster), roster_digest(roster), lease.id, execution["id"]),
        )
        _stale(conn, execution["id"])

        receipt = _reconcile(conn, execution["id"])

        handed = lock_plan_execution(conn, execution["id"])
        assert receipt["outcome"] == "review_handoff"
        assert receipt["released_lease_ids"] == [lease.id]
        assert receipt["review_bundle_id"] == bundle["bundle_id"]
        assert not get_claim(conn, lease.id).is_active
        assert handed["state"] == "awaiting_walk_review"
        assert handed["machine_lease_id"] is None
        assert handed["session_id"] == STEERING


def test_parked_owner_keeps_its_walk():
    with test_database() as conn:
        execution, _bundle, _capture = _awaiting_review(conn, 4942)
        register_session_actor(conn, "review-session")
        conn.execute(
            "UPDATE harness_sessions SET mode='parked' WHERE session_id=%s",
            ("review-session",),
        )
        _stale(conn, execution["id"])
        with pytest.raises(QaPlanExecutionStateError) as refused:
            _reconcile(conn, execution["id"])
        assert "qa_reconcile_owner_parked" in str(refused.value)
        assert lock_plan_execution(conn, execution["id"])["session_id"] == (
            "review-session"
        )


def test_parked_owner_does_not_hold_an_ended_walk():
    with test_database() as conn:
        execution, bundle, _capture = _awaiting_review(conn, 4945)
        conn.execute(
            "UPDATE qa_plan_executions SET state='aborted',completed_at=CURRENT_TIMESTAMP "
            "WHERE id=%s",
            (execution["id"],),
        )
        register_session_actor(conn, "review-session")
        conn.execute(
            "UPDATE harness_sessions SET mode='parked' WHERE session_id=%s",
            ("review-session",),
        )
        conn.commit()

        receipt = _reconcile(conn, execution["id"])

        assert receipt["outcome"] == "review_handoff"
        assert receipt["review_bundle_id"] == bundle["bundle_id"]
        assert lock_plan_execution(conn, execution["id"])["state"] == "aborted"


def test_sessionless_operator_settles_but_cannot_take_a_review():
    with test_database() as conn:
        judgeable, _bundle, _capture = _awaiting_review(conn, 4943)
        _stale(conn, judgeable["id"])
        with pytest.raises(QaPlanExecutionStateError) as refused:
            _reconcile(conn, judgeable["id"], session_id=None)
        assert "qa_reconcile_review_needs_session" in str(refused.value)
        assert lock_plan_execution(conn, judgeable["id"])["state"] == (
            "awaiting_walk_review"
        )

    with test_database() as conn:
        empty, bundle, _capture = _awaiting_review(conn, 4944)
        _without_artifacts(conn, bundle["bundle_id"])
        _stale(conn, empty["id"])
        receipt = _reconcile(conn, empty["id"], session_id=None)
        settled = lock_plan_execution(conn, empty["id"])
        assert receipt["outcome"] == "aborted"
        assert settled["state"] == "aborted"
        assert settled["session_id"] == "review-session"
        audit = _receipt(conn, receipt["reconciliation_id"])
        assert audit["session_id"] is None
        assert audit["reason"] == REASON


def _request(session_id, actor_id="2"):
    return FunctionCallRequest(
        function="qa.plan_execution.reconcile",
        actor=ActorContext(actor_id=actor_id, session_id=session_id),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"execution_id": "unknown", "reason": REASON},
    )


def test_ordinary_session_and_unprivileged_sessionless_caller_are_refused():
    with test_database() as conn:
        register_session_actor(conn, "ordinary-session")
        project_id = resolve_project_id(conn, "yoke")
        with pytest.raises(SessionError) as refused:
            _require_operator(conn, _request("ordinary-session"), project_id)
        assert refused.value.code == "steering_seat_required"
        assert "yoke claims steering acquire --project" in refused.value.message
        with pytest.raises(PermissionDenied):
            _require_operator(conn, _request("", actor_id=None), project_id)
