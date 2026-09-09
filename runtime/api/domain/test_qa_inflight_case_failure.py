"""A case its execution died on reads as failed, never as still queued.

A runner that raises before recording anything leaves its requirement with
no run at all, and every latest-run projection reads that absence as
"queued" — the same answer a case nobody ever tried gets. The execution
ending short of its roster is the evidence that this one was tried, so
terminal settlement records that failure against the case it was on.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.deployment_run_qa_plan_execution_test_support import (
    RUN_ID,
    command_plan,
    deployment_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_attachments import materialize_for_deployment_run
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_execution_continuation import (
    CASE_EXECUTION_ERROR_REASON,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)


def _abandoned_execution(conn: Any) -> tuple[int, int]:
    """Start a deployment-run execution that records nothing, then abort it."""
    deployment_run(conn)
    plan_id = command_plan(conn)
    materialized = materialize_for_deployment_run(
        conn,
        deployment_run_id=RUN_ID,
        plan="deployment-smoke",
        project="yoke",
    )
    requirement_id = int(materialized["created_requirement_ids"][0])
    execution = begin_plan_execution(
        conn,
        deployment_run_id=RUN_ID,
        actor_id="7",
        session_id="deployment-qa",
    )
    finish_plan_execution(
        conn,
        lock_plan_execution(conn, str(execution["id"])),
        state="aborted",
        reason=CASE_EXECUTION_ERROR_REASON,
    )
    return plan_id, requirement_id


def test_abandoned_case_records_its_failure_against_the_requirement() -> None:
    with test_database() as conn:
        _, requirement_id = _abandoned_execution(conn)
        run = conn.execute(
            "SELECT performed_by,verdict,verdict_reason,case_outcome,"
            "execution_status FROM qa_runs WHERE qa_requirement_id=%s",
            (requirement_id,),
        ).fetchone()

    assert run is not None
    assert run["performed_by"] == "worktree_run"
    assert run["verdict"] == "error"
    assert run["case_outcome"] == "failed"
    assert run["execution_status"] is None
    assert CASE_EXECUTION_ERROR_REASON in run["verdict_reason"]


def test_plan_readback_shows_the_failure_rather_than_queued() -> None:
    with test_database() as conn:
        plan_id, _ = _abandoned_execution(conn)
        plan = get_plan(conn, plan_id=plan_id, deployment_run_id=RUN_ID)

    case = plan["cases"][0]
    assert case["last_result"]["outcome"] == "failed"
    assert case["last_result"]["run_id"] is not None


def test_a_case_that_recorded_its_own_run_is_left_alone() -> None:
    with test_database() as conn:
        deployment_run(conn)
        command_plan(conn)
        materialized = materialize_for_deployment_run(
            conn,
            deployment_run_id=RUN_ID,
            plan="deployment-smoke",
            project="yoke",
        )
        requirement_id = int(materialized["created_requirement_ids"][0])
        execution = begin_plan_execution(
            conn,
            deployment_run_id=RUN_ID,
            actor_id="7",
            session_id="deployment-qa",
        )
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
            "verdict,case_outcome,created_at) "
            "VALUES(%s,'worktree_run','plan_case','fail','failed',%s)",
            (requirement_id, "2099-01-01T00:00:00Z"),
        )
        finish_plan_execution(
            conn,
            lock_plan_execution(conn, str(execution["id"])),
            state="aborted",
            reason=CASE_EXECUTION_ERROR_REASON,
        )
        runs = conn.execute(
            "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s",
            (requirement_id,),
        ).fetchall()

    assert [row["verdict"] for row in runs] == ["fail"]
