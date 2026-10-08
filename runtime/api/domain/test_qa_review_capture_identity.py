"""A review judges its capture without manufacturing another execution."""

import pytest

from runtime.api.domain.test_qa_plan_agent_review import _review_execution
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_capture_settlement import stamp_reviewed_capture
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review


def test_review_preserves_attempt_count_start_and_evidence():
    with test_database() as conn:
        execution, requirement_id, capture_id = _review_execution(conn, 4581)
        before = conn.execute(
            "SELECT started_at,raw_result FROM qa_runs WHERE id=%s", (capture_id,)
        ).fetchone()
        bundle = begin_plan_review(conn, execution)
        arguments = dict(
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=[
                dict(
                    requirement_id=requirement_id,
                    verdict="pass",
                    rationale="The actual captured frame proves the outcome.",
                )
            ],
            reviewer_actor_id=None,
            reviewer_session_id="review-session",
        )
        first = submit_plan_review(conn, execution, **arguments)
        replay = submit_plan_review(conn, execution, **arguments)
        assert first["verdicts"] == replay["verdicts"]
        assert first["verdicts"][0]["review_run_id"] == capture_id
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
                (requirement_id,),
            ).fetchone()[0]
            == 1
        )
        after = conn.execute(
            "SELECT started_at,raw_result FROM qa_runs WHERE id=%s", (capture_id,)
        ).fetchone()
        assert tuple(after) == tuple(before)
        audit = conn.execute(
            "SELECT capture_run_id,review_run_id FROM qa_plan_review_verdicts "
            "WHERE bundle_id=%s",
            (bundle["bundle_id"],),
        ).fetchone()
        assert tuple(audit) == (capture_id, capture_id)


def test_capture_review_refuses_wrong_requirement_without_writes():
    with test_database() as conn:
        _execution, requirement_id, capture_id = _review_execution(conn, 4582)
        with pytest.raises(ValueError, match="qa_review_capture_mismatch"):
            stamp_reviewed_capture(
                conn,
                dict(requirement_id=requirement_id + 1, capture_run_id=capture_id),
                verdict="pass",
                rationale="Wrong subject",
                created_at="2026-07-30T00:00:00Z",
            )
        assert (
            conn.execute(
                "SELECT verdict FROM qa_runs WHERE id=%s", (capture_id,)
            ).fetchone()[0]
            is None
        )
