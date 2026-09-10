"""What actually settles a pending QA review request, versus what doesn't.

A completed walk's own undetermined result is never itself grounds to
withdraw the review it raised (see test_qa_execution_decision_disposition).
This module proves what *does* settle it: a later conclusive run, a waiver,
or replaying the same review bundle recovers exactly one pending request --
and what still must not: an older, unrelated run.
"""

from __future__ import annotations

from runtime.api.domain.test_qa_execution_decision_disposition import (
    _status,
    _undetermined_walk,
)
from runtime.api.domain.test_qa_plan_agent_review import _review_execution
from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.qa_review_requests import ensure_qa_review_request


def test_a_completed_undetermined_review_survives_inbox_convergence() -> None:
    with test_database() as conn:
        execution, request_id = _undetermined_walk(
            conn, item_id=4808, session_id="convergence-session"
        )
        requirement_ids = [case["requirement_id"] for case in execution["roster"]]
        advance_plan_execution(
            conn,
            execution,
            ordinal=1,
            requirement_id=requirement_ids[1],
            result={"requirement_id": requirement_ids[1], "verdict": "pass"},
        )
        finish_plan_execution(
            conn, execution, state="completed", reason="qa-plan-agent-review-complete"
        )
        assert _status(conn, request_id)[0] == "pending"

        result = dispose_ended_decision_requests(conn)

        assert _status(conn, request_id)[0] == "pending"
        assert request_id not in [row["request_id"] for row in result["withdrawn"]]


def test_a_later_conclusive_run_supersedes_the_review() -> None:
    with test_database() as conn:
        execution, request_id = _undetermined_walk(
            conn, item_id=4809, session_id="supersede-session"
        )
        requirement_id = execution["roster"][0]["requirement_id"]
        conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "started_at, completed_at, created_at) "
            "VALUES (%s, 'human_review', 'plan_case', 'fail', "
            "'Reviewed and rejected.', '2026-07-28T18:43:00Z', "
            "'2026-07-28T18:43:00Z', '2026-07-28T18:43:00Z')",
            (requirement_id,),
        )
        conn.commit()

        result = dispose_ended_decision_requests(conn)

        status, reason = _status(conn, request_id)
        assert status == "withdrawn"
        assert "conclusive result" in reason
        assert [row["request_id"] for row in result["withdrawn"]] == [request_id]


def test_an_older_run_cannot_supersede_a_later_review() -> None:
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4810)
        requirement_id = requirement_ids[0]
        conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "started_at, completed_at, created_at) "
            "VALUES (%s, 'human_review', 'plan_case', 'fail', "
            "'An earlier, unrelated rejection.', '2026-07-28T18:40:00Z', "
            "'2026-07-28T18:40:00Z', '2026-07-28T18:40:00Z')",
            (requirement_id,),
        )
        execution = begin_plan_execution(
            conn,
            item_id=4810,
            transition_id="implemented",
            actor_id="7",
            session_id="later-review-session",
        )
        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=requirement_id,
            result={"requirement_id": requirement_id, "verdict": "undetermined"},
        )
        run_id = conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "started_at, completed_at, created_at) "
            "VALUES (%s, 'agent', 'plan_case', 'undetermined', "
            "'The walker never reached the surface.', "
            "'2026-07-28T18:42:00Z', '2026-07-28T18:42:00Z', "
            "'2026-07-28T18:42:00Z') RETURNING id",
            (requirement_id,),
        ).fetchone()[0]
        request, _created = ensure_qa_review_request(
            conn, requirement_id=int(requirement_id), run_id=int(run_id)
        )
        request_id = int(request["id"])
        second_requirement_id = execution["roster"][1]["requirement_id"]
        advance_plan_execution(
            conn,
            execution,
            ordinal=1,
            requirement_id=second_requirement_id,
            result={"requirement_id": second_requirement_id, "verdict": "pass"},
        )
        finish_plan_execution(
            conn, execution, state="completed", reason="qa-plan-agent-review-complete"
        )

        result = dispose_ended_decision_requests(conn)

        assert _status(conn, request_id)[0] == "pending"
        assert request_id not in [row["request_id"] for row in result["withdrawn"]]


def test_waiving_the_requirement_settles_its_pending_review() -> None:
    with test_database() as conn:
        execution, request_id = _undetermined_walk(
            conn, item_id=4811, session_id="waive-session"
        )
        requirement_id = execution["roster"][0]["requirement_id"]
        conn.execute(
            "UPDATE qa_requirements SET waived_at='2026-07-28T18:44:00Z', "
            "waiver_rationale='No longer relevant.' WHERE id=%s",
            (requirement_id,),
        )
        conn.commit()

        result = dispose_ended_decision_requests(conn)

        status, reason = _status(conn, request_id)
        assert status == "withdrawn"
        assert "was waived" in reason
        assert [row["request_id"] for row in result["withdrawn"]] == [request_id]


def test_replaying_the_review_bundle_recovers_one_pending_request() -> None:
    with test_database() as conn:
        execution, requirement_id, _capture_run_id = _review_execution(conn, 4531)
        bundle = begin_plan_review(conn, execution)
        verdicts = [
            {
                "requirement_id": requirement_id,
                "verdict": "undetermined",
                "rationale": "The frame does not confirm the outcome.",
            }
        ]
        first = submit_plan_review(
            conn,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=verdicts,
            reviewer_actor_id=None,
            reviewer_session_id="review-session",
        )
        request_id = int(first["verdicts"][0]["decision_request_id"])

        # Simulate the historical defect: something (the old buggy
        # completion-time disposal, an old convergence sweep) already
        # withdrew the review this completed execution had raised. How it
        # got withdrawn is not this test's subject; that a completed walk's
        # replay recovers a fresh pending request from here is.
        conn.execute(
            "UPDATE decision_requests SET status='withdrawn', "
            "withdrawal_reason='simulated pre-fix withdrawal', "
            "withdrawn_at='2026-07-29T00:05:00Z' WHERE id=%s",
            (request_id,),
        )
        conn.commit()
        assert _status(conn, request_id)[0] == "withdrawn"

        replay = submit_plan_review(
            conn,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=verdicts,
            reviewer_actor_id=None,
            reviewer_session_id="review-session",
        )

        recovered_id = int(replay["verdicts"][0]["decision_request_id"])
        assert recovered_id != request_id
        assert _status(conn, recovered_id)[0] == "pending"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_plan_review_verdicts WHERE bundle_id=%s",
                (bundle["bundle_id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s "
                "AND performed_by='agent'",
                (requirement_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM decision_requests WHERE kind='qa_needs_review' "
                "AND subject_key=%s AND status='pending'",
                (str(requirement_id),),
            ).fetchone()[0]
            == 1
        )
