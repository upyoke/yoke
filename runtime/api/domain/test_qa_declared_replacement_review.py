"""Declared replacements through the real verdict paths.

An item case's agent review and a run stage's human acceptance both see the
failed case discharged on the corrected case's passing verdict, and never
before it.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_qa_plan_agent_review import _review_execution
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from runtime.api.fixtures.qa_declared_replacement_fixture import (
    corrected_case,
    declare,
    requirement_row,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.deployment_qa_source_obligation import unsatisfied_blocking
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.qa_requirement_replacement import discharge_declared_replacements


def _item_case_with_failed_attempt(conn: Any, item_id: int) -> tuple[dict, int, int]:
    execution, corrected_id, _capture = _review_execution(conn, item_id)
    failed_id = corrected_case(
        conn, failed_id=corrected_id, case_key="review-frame-first-attempt"
    )
    record_case_verdict(conn, failed_id, "fail", evidence=False)
    declare(conn, failed_id, "review-frame", [corrected_id])
    return execution, corrected_id, failed_id


def _review(conn: Any, execution: dict, requirement_id: int, verdict: str) -> dict:
    bundle = begin_plan_review(conn, execution)
    assert [int(case["requirement_id"]) for case in bundle["cases"]] == [requirement_id]
    return submit_plan_review(
        conn,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": verdict,
                "rationale": f"Recorded {verdict} from the supplied evidence.",
            }
        ],
        reviewer_actor_id=None,
        reviewer_session_id="review-session",
    )


def _unsatisfied_ids(conn: Any, item_id: int) -> set[int]:
    result = unsatisfied_blocking(conn, item_id=item_id, target_status="done")
    return {int(row["id"]) for row in result.rows}


def test_item_review_pass_supersedes_the_failed_item_case_in_its_commit() -> None:
    with test_database() as conn:
        execution, corrected_id, failed_id = _item_case_with_failed_attempt(conn, 4621)
        assert [
            int(row["requirement_id"])
            for row in ordered_plan_requirements(
                conn, item_id=4621, transition_id="implemented"
            )
        ] == [corrected_id]
        assert failed_id in _unsatisfied_ids(conn, 4621)

        result = _review(conn, execution, corrected_id, "pass")

        assert [entry["requirement_id"] for entry in result["superseded_by_replacement"]] == [
            failed_id
        ]
        assert requirement_row(conn, failed_id)["superseded_by_requirement_id"] == corrected_id
        assert failed_id not in _unsatisfied_ids(conn, 4621)


def test_item_review_fail_keeps_the_failed_item_case_blocking() -> None:
    with test_database() as conn:
        execution, corrected_id, failed_id = _item_case_with_failed_attempt(conn, 4622)

        result = _review(conn, execution, corrected_id, "fail")

        assert result["superseded_by_replacement"] == []
        row = requirement_row(conn, failed_id)
        assert row["superseded_by_requirement_id"] is None
        assert row["replacement_requirement_id"] == corrected_id
        assert failed_id in _unsatisfied_ids(conn, 4622)


def _run_stage_execution(conn: Any, run_id: str, verdict: str) -> list[int]:
    """Execute a run-scoped stage's roster to one verdict; discharge on a pass."""
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        actor_id="2",
        session_id="run-qa",
    )
    ran: list[int] = []
    for ordinal, entry in enumerate(execution["roster"]):
        requirement_id = int(entry["requirement_id"])
        qa_run_id = record_case_verdict(conn, requirement_id, verdict, evidence=True)
        advance_plan_execution(
            conn,
            execution,
            ordinal=ordinal,
            requirement_id=requirement_id,
            result={
                "requirement_id": requirement_id,
                "verdict": verdict,
                "case_outcome": "passed" if verdict == "pass" else "failed",
                "run_id": qa_run_id,
            },
        )
        ran.append(requirement_id)
    if verdict == "pass":
        discharge_declared_replacements(conn, ran)
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    conn.commit()
    return ran


def test_human_acceptance_is_requested_only_after_the_replacement_passes(test_db) -> None:
    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _plan,
        _seed_run,
        _stages,
    )
    from runtime.api.domain.test_deployment_qa_stage_human_review import _human_actor
    from yoke_core.domain.decision_request_resolution import resolve_decision_request
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )

    run_id, reviewer = "run-replacement-human", 9812
    _human_actor(test_db, reviewer)
    stages = _stages(
        _plan(test_db, "replacement-human-smoke"),
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [reviewer]},
        },
    )
    stages[1]["scope"] = "run"
    _seed_run(test_db, run_id=run_id, stages=stages, members=())
    materialize_deployment_qa_stage(
        test_db, deployment_run_id=run_id, deployment_stage="item-qa"
    )
    [failed_id] = _run_stage_execution(test_db, run_id, "fail")
    corrected_id = corrected_case(test_db, failed_id=failed_id, case_key="smoke-fixed")
    declare(test_db, failed_id, "smoke-fixed", [corrected_id])

    def status() -> dict[str, Any]:
        return deployment_qa_stage_status(
            test_db, run_id=run_id, stage_name="item-qa", member_item_id=None
        )

    waiting = status()
    assert not waiting["accepted"] and waiting["request_id"] is None

    assert _run_stage_execution(test_db, run_id, "pass") == [corrected_id]
    assert requirement_row(test_db, failed_id)["superseded_by_requirement_id"] == corrected_id
    pending = status()
    assert not pending["accepted"] and pending["request_id"] is not None

    resolve_decision_request(
        test_db,
        int(pending["request_id"]),
        actor_id=reviewer,
        action="approve",
        note="The corrected case's evidence satisfies the stage.",
    )
    assert status()["accepted"]
