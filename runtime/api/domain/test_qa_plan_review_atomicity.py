"""Transaction ownership for batched QA review submission."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_qa_plan_agent_review import _review_execution
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa_plan_review_submission, qa_review_requests
from yoke_core.domain.coordination_leases import acquire_lease, get_lease
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.schema_init_tables import create_governed_tables


def _undetermined(requirement_id: int) -> list[dict[str, object]]:
    return [
        {
            "requirement_id": requirement_id,
            "verdict": "undetermined",
            "rationale": "The supplied evidence is not decisive.",
        }
    ]


def test_non_mission_review_does_not_retain_a_machine_lease() -> None:
    with test_database() as conn:
        execution, _requirement_id, _capture_run_id = _review_execution(conn, 4540)
        create_governed_tables(conn)
        lease = acquire_lease(
            conn,
            1,
            "TEST_MAC:ordinary-review",
            "review-session",
            actor_id="7",
        )
        conn.execute(
            "UPDATE qa_plan_executions SET machine_lease_id=%s WHERE id=%s",
            (lease.id, execution["id"]),
        )
        conn.commit()
        execution["machine_lease_id"] = lease.id

        bundle = begin_plan_review(conn, execution)

        assert bundle is not None
        assert execution["state"] == "awaiting_agent_review"
        assert execution["machine_lease_id"] is None
        assert get_lease(conn, lease.id).is_active is False


def test_request_failure_rolls_back_entire_review_submission(monkeypatch) -> None:
    with test_database() as conn:
        execution, requirement_id, capture_run_id = _review_execution(conn, 4541)
        bundle = begin_plan_review(conn, execution)
        create_governed_tables(conn)
        lease = acquire_lease(
            conn,
            1,
            "TEST_MAC:review-atomicity",
            "review-session",
            actor_id="7",
        )
        conn.execute(
            "UPDATE qa_plan_executions SET machine_lease_id=%s WHERE id=%s",
            (lease.id, execution["id"]),
        )
        conn.commit()
        execution["machine_lease_id"] = lease.id
        original = qa_review_requests.ensure_qa_review_request

        def create_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected request failure")

        monkeypatch.setattr(
            qa_review_requests,
            "ensure_qa_review_request",
            create_then_fail,
        )
        with pytest.raises(RuntimeError, match="injected request failure"):
            qa_plan_review_submission.submit_plan_review(
                conn,
                execution,
                bundle_id=bundle["bundle_id"],
                bundle_digest=bundle["bundle_digest"],
                verdicts=_undetermined(requirement_id),
                reviewer_actor_id=None,
                reviewer_session_id="review-session",
            )

        bundle_state = conn.execute(
            "SELECT state FROM qa_plan_review_bundles WHERE id=%s",
            (bundle["bundle_id"],),
        ).fetchone()[0]
        execution_state = conn.execute(
            "SELECT state FROM qa_plan_executions WHERE id=%s",
            (execution["id"],),
        ).fetchone()[0]
        assert bundle_state == "pending"
        assert execution_state == "awaiting_agent_review"
        assert execution["state"] == "awaiting_agent_review"
        assert execution["machine_lease_id"] == lease.id
        assert get_lease(conn, lease.id).is_active is True
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_plan_review_verdicts WHERE bundle_id=%s",
                (bundle["bundle_id"],),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_runs "
                "WHERE qa_requirement_id=%s AND performed_by='agent'",
                (requirement_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM decision_requests "
                "WHERE kind='qa_needs_review' AND subject_key=%s",
                (str(requirement_id),),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT verdict FROM qa_runs WHERE id=%s",
                (capture_run_id,),
            ).fetchone()[0]
            is None
        )


def test_telemetry_failure_cannot_undo_committed_review(monkeypatch) -> None:
    with test_database() as conn:
        execution, requirement_id, capture_run_id = _review_execution(conn, 4542)
        bundle = begin_plan_review(conn, execution)

        def fail_telemetry(*_args, **_kwargs):
            raise RuntimeError("injected telemetry failure")

        monkeypatch.setattr(
            qa_plan_review_submission,
            "_emit_review_events",
            fail_telemetry,
        )
        result = qa_plan_review_submission.submit_plan_review(
            conn,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=[
                {
                    "requirement_id": requirement_id,
                    "verdict": "pass",
                    "rationale": "The supplied evidence satisfies the case.",
                }
            ],
            reviewer_actor_id="7",
            reviewer_session_id="review-session",
        )

        assert result["state"] == "passed"
        assert execution["state"] == "completed"
        assert (
            conn.execute(
                "SELECT state FROM qa_plan_review_bundles WHERE id=%s",
                (bundle["bundle_id"],),
            ).fetchone()[0]
            == "completed"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_plan_review_verdicts WHERE bundle_id=%s",
                (bundle["bundle_id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT verdict FROM qa_runs WHERE id=%s",
                (capture_run_id,),
            ).fetchone()[0]
            == "pass"
        )
