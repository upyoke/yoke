"""Which QA run the stage gate counts evidence on.

A case can carry two runs: the capture run the plan execution recorded, and
a later review run that re-graded it. The gate accepts the newest run's
verdict, so that run is the one its evidence question is about — but the
evidence itself may legitimately sit on either, and a refusal has to say
which runs it looked at.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)

MEMBER = 9811


def _capture_run(conn: Any, run_id: str, requirement_id: int, *, evidence: bool) -> int:
    """Execute the member's plan once; return the run the execution recorded."""
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="member-qa",
    )
    qa_run_id = record_case_verdict(conn, requirement_id, "pass", evidence=evidence)
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": qa_run_id,
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    conn.commit()
    return qa_run_id


def _status(conn: Any, run_id: str) -> dict[str, Any]:
    return deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=MEMBER
    )


def test_evidence_on_the_run_carrying_the_accepted_verdict_is_counted(
    test_db,
) -> None:
    """The review run's own artifacts satisfy the gate that accepted it.

    This is where a reviewer attaches evidence, and reading the execution
    record instead asked about the capture run, refusing three re-drives of
    a member whose evidence was already attached to the accepted pass.
    """
    run_id = "run-evidence-accepted"
    requirement_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    _capture_run(test_db, run_id, requirement_id, evidence=False)
    record_case_verdict(test_db, requirement_id, "pass", evidence=True)

    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]


def test_evidence_on_only_the_execution_named_run_still_passes(test_db) -> None:
    """The execution-scoped walk stays as the fallback it exists for.

    A case whose artifacts were captured when it ran, and which a later
    review re-graded without re-capturing, keeps passing on the evidence the
    execution record names.
    """
    run_id = "run-evidence-execution"
    requirement_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    capture_run_id = _capture_run(test_db, run_id, requirement_id, evidence=True)
    review_run_id = record_case_verdict(test_db, requirement_id, "pass", evidence=False)
    assert review_run_id != capture_run_id

    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]


def test_a_pass_with_artifacts_nowhere_refuses_and_names_the_runs_inspected(
    test_db,
) -> None:
    """The evidence requirement holds, and the refusal says where it looked."""
    run_id = "run-evidence-missing"
    requirement_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    capture_run_id = _capture_run(test_db, run_id, requirement_id, evidence=False)
    review_run_id = record_case_verdict(test_db, requirement_id, "pass", evidence=False)

    status = _status(test_db, run_id)
    assert not status["accepted"]
    reason = next(
        entry for entry in status["reasons"] if "no attached evidence" in entry
    )
    assert f"#{review_run_id}" in reason
    assert f"#{capture_run_id}" in reason
    assert f"attach evidence to qa_run #{review_run_id}" in reason
