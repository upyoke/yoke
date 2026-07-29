"""Replay immutability for completed batched agent inspection."""

from runtime.api.domain.test_qa_plan_agent_review import _review_execution
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review


def test_completed_submission_replay_preserves_reviewer_and_single_verdict() -> None:
    with test_database() as conn:
        execution, requirement_id, _capture_run_id = _review_execution(conn, 4530)
        bundle = begin_plan_review(conn, execution)
        verdicts = [
            {
                "requirement_id": requirement_id,
                "verdict": "pass",
                "rationale": "The captured frame matches the expected outcome.",
            }
        ]
        first = submit_plan_review(
            conn,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=verdicts,
            reviewer_actor_id="7",
            reviewer_session_id="review-session",
        )
        replay = submit_plan_review(
            conn,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=verdicts,
            reviewer_actor_id="99",
            reviewer_session_id="different-reviewer",
        )

        stored = conn.execute(
            "SELECT reviewer_actor_id,reviewer_session_id "
            "FROM qa_plan_review_bundles WHERE id=%s",
            (bundle["bundle_id"],),
        ).fetchone()
        assert tuple(stored) == ("7", "review-session")
        assert replay["verdicts"] == first["verdicts"]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_plan_review_verdicts WHERE bundle_id=%s",
                (bundle["bundle_id"],),
            ).fetchone()[0]
            == 1
        )
