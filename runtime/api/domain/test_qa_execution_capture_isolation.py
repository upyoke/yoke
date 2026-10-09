"""Ending an older execution cannot judge an unrelated newer capture."""

import json

import pytest

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_run
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.qa_capture_settlement import stamp_reviewed_capture


@pytest.mark.parametrize(
    "termination", ["review", "abort", "judged_result", "unbound_result"]
)
def test_execution_termination_only_settles_its_bound_capture(test_db, termination):
    execution, requirement_id, old_id = captured_plan_review(test_db, 4873)
    bundle = begin_plan_review(test_db, execution) if termination == "review" else None
    newer_id = int(
        insert_qa_run(
            test_db,
            qa_requirement_id=requirement_id,
            performed_by="host_control",
            verdict=None,
            case_outcome="needs_review",
            execution_status="captured",
            raw_result="newer evidence",
            started_at="2026-07-30T00:00:00Z",
            completed_at="2026-07-30T00:00:01Z",
        )["id"]
    )
    before = dict(
        test_db.execute("SELECT * FROM qa_runs WHERE id=%s", (newer_id,)).fetchone()
    )
    count = test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
    if termination == "review":
        result = submit_plan_review(
            test_db,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=[
                {
                    "requirement_id": requirement_id,
                    "verdict": "pass",
                    "rationale": "Only the frozen older capture passes.",
                }
            ],
            reviewer_actor_id=None,
            reviewer_session_id="review-session",
        )
        assert result["verdicts"][0]["review_run_id"] == old_id
    elif termination == "abort":
        finish_plan_execution(
            test_db, execution, state="aborted", reason="operator-abort"
        )
        assert (
            test_db.execute(
                "SELECT verdict FROM qa_runs WHERE id=%s", (old_id,)
            ).fetchone()[0]
            == "error"
        )
    else:
        result = {"requirement_id": requirement_id, "case_outcome": "needs_review"}
        if termination == "judged_result":
            stamp_reviewed_capture(
                test_db,
                {"requirement_id": requirement_id, "capture_run_id": old_id},
                verdict="pass",
                rationale="Already judged result.",
                created_at="2026-07-29T00:00:02Z",
            )
            result.update(verdict="pass", case_outcome="passed", run_id=old_id)
        test_db.execute(
            "UPDATE qa_plan_execution_results SET result_json=%s WHERE execution_id=%s",
            (json.dumps(result), execution["id"]),
        )
        finish_plan_execution(
            test_db, execution, state="completed", reason="test-complete"
        )
        assert test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (old_id,)
        ).fetchone()[0] == ("pass" if termination == "judged_result" else None)
    assert (
        dict(
            test_db.execute("SELECT * FROM qa_runs WHERE id=%s", (newer_id,)).fetchone()
        )
        == before
    )
    plan_id = test_db.execute(
        "SELECT plan_id FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    proof = get_plan(test_db, plan_id=plan_id)
    assert proof["cases"][0]["last_result"]["run_id"] == newer_id
    assert proof["union"] == {"satisfied": False, "counts": {"needs_review": 1}}
    stamp_reviewed_capture(
        test_db,
        {"requirement_id": requirement_id, "capture_run_id": newer_id},
        verdict="fail",
        rationale="Its own later review fails.",
        created_at="2026-07-30T00:00:02Z",
    )
    assert get_plan(test_db, plan_id=plan_id)["union"] == {
        "satisfied": False,
        "counts": {"failed": 1},
    }
    assert test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == count
