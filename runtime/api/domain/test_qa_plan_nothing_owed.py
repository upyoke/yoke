"""A plan run that owes no case refuses and names the stage's real blocker."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _project,
    seed_session,
)
from runtime.api.domain.test_qa_aborted_review_ownership import OWNER, _fail_run
from runtime.api.domain.test_qa_capture_pending_review import (
    NOW,
    _seed_pending,
    _submit,
)
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_nothing_owed import QaPlanNothingOwed
from yoke_core.domain.qa_plan_settled_review import open_unsettled_roster


def _count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0]


def test_review_held_roster_refuses_with_review_begin(test_db):
    _project(test_db)
    seed_session(test_db, OWNER)
    run_id = "run-nothing-owed-review"
    execution, _bundle, requirement_id = _seed_pending(test_db, run_id, "item")
    _fail_run(test_db, execution)
    before = _count(test_db)

    with pytest.raises(QaPlanNothingOwed) as refused:
        begin_plan_execution(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=execution["deployment_stage"],
            deployment_member_item_id=execution["deployment_member_item_id"],
            actor_id="2",
            session_id=OWNER,
        )

    test_db.rollback()
    message = str(refused.value)
    assert "qa_plan_nothing_owed: nothing owed" in message
    assert f"#{requirement_id}" in message
    assert (f"yoke qa plan review-begin --execution-id {execution['id']}") in message
    assert _count(test_db) == before


def test_a_newer_capture_reopens_a_reviewed_pass(test_db):
    """A batch pass that judged an older capture no longer settles the case."""
    _project(test_db)
    execution, bundle, requirement_id = _seed_pending(
        test_db, "run-nothing-owed-newer", "item"
    )
    _submit(test_db, execution, bundle, requirement_id, "pass")
    scope = dict(
        item_id=None,
        transition_id=None,
        deployment_run_id=execution["deployment_run_id"],
        deployment_stage=execution["deployment_stage"],
        deployment_member_item_id=execution["deployment_member_item_id"],
    )
    reprint, kept = open_unsettled_roster(test_db, execution["roster"], **scope)
    assert reprint is not None and kept == []

    later = NOW.replace("00:00:00", "01:00:00")
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
        "execution_status,case_outcome,raw_result,started_at,completed_at,"
        "created_at) VALUES(%s,'browser_substrate','method_case','captured',"
        "'needs_review','{}',%s,%s,%s)",
        (requirement_id, later, later, later),
    )
    test_db.commit()

    reprint, kept = open_unsettled_roster(test_db, execution["roster"], **scope)
    assert reprint is None
    assert [int(row["requirement_id"]) for row in kept] == [requirement_id]
