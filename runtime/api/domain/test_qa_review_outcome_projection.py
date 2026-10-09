"""Final judgments drive readiness while the original capture stays intact."""

import pytest

from runtime.api.domain.qa_review_seed import _seed_undetermined_review
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.qa_catalog_reads import list_plans
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.qa_review_requests import ensure_qa_review_request


def _capture(conn, run_id):
    return dict(
        conn.execute(
            "SELECT raw_result,started_at,completed_at,execution_status,case_outcome "
            "FROM qa_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
    )


def _assert_projection(conn, plan_id, run_id, outcome):
    detail = get_plan(conn, plan_id=plan_id)
    proof = detail["cases"][0]["last_result"]
    listed = next(
        row for row in list_plans(conn, project="yoke") if row["id"] == plan_id
    )
    assert proof["run_id"] == run_id
    assert proof["outcome"] == listed["last_outcome"] == outcome
    assert detail["union"] == {"satisfied": outcome == "passed", "counts": {outcome: 1}}


@pytest.mark.parametrize(
    "verdict,outcome",
    [("pass", "passed"), ("fail", "failed"), ("undetermined", "needs_review")],
)
def test_agent_judgment_projects_same_capture_outcome(test_db, verdict, outcome):
    execution, requirement_id, capture_id = captured_plan_review(test_db, 4871)
    before = _capture(test_db, capture_id)
    count = test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
    bundle = begin_plan_review(test_db, execution)
    result = submit_plan_review(
        test_db,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": verdict,
                "rationale": "Judgment of the supplied capture.",
            }
        ],
        reviewer_actor_id=None,
        reviewer_session_id="review-session",
    )
    plan_id = test_db.execute(
        "SELECT plan_id FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    _assert_projection(test_db, plan_id, capture_id, outcome)
    assert result["verdicts"][0]["review_run_id"] == capture_id
    assert _capture(test_db, capture_id) == before
    assert test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == count


def test_human_resolution_projects_same_pending_capture_as_passed(test_db):
    seeded = _seed_undetermined_review(
        test_db,
        item_id=4872,
        plan_slug="human-capture-outcome",
        decider_roles=("owner",),
        performed_by="browser_substrate",
    )
    replace_plan_cases(
        test_db,
        plan_id=seeded["plan_id"],
        cases=[
            {
                "case_key": "checkout-flow",
                "position": 1,
                "method_id": "browser-inspection",
                "instructions": "Inspect the saved screen.",
                "expected_outcome": "Saved state is visible.",
                "method_config": {
                    "steps": [
                        {"action": "navigate", "route": "/"},
                        {"action": "screenshot", "capture": True},
                    ]
                },
            }
        ],
    )
    test_db.execute(
        "UPDATE qa_runs SET case_outcome='needs_review',execution_status='captured',"
        "raw_result='captured evidence' WHERE id=%s",
        (seeded["run_id"],),
    )
    test_db.commit()
    before = _capture(test_db, seeded["run_id"])
    count = test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
    request, _ = ensure_qa_review_request(
        test_db,
        requirement_id=seeded["requirement_id"],
        run_id=seeded["run_id"],
        originator_actor_id=seeded["originator"],
    )
    _assert_projection(test_db, seeded["plan_id"], seeded["run_id"], "needs_review")
    resolved = resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=seeded["deciders"][0],
        action="approve",
        note="The saved state is visible in the capture.",
    )
    assert resolved["status"] == "resolved"
    _assert_projection(test_db, seeded["plan_id"], seeded["run_id"], "passed")
    assert _capture(test_db, seeded["run_id"]) == before
    assert test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == count
