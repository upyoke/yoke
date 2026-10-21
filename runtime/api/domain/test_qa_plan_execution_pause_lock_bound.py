"""A pause behind a held execution row refuses by name instead of queueing."""

from __future__ import annotations

from time import monotonic

from runtime.api.domain.test_qa_execution_request_subject import (
    SESSION,
    _shared_execution,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON
from yoke_core.domain.yoke_function_dispatch import dispatch


def test_pause_refuses_with_recovery_when_the_execution_row_stays_locked(test_db):
    run_id = "run-pause-lock-bound"
    execution = _shared_execution(test_db, run_id, (9301, 9302))
    holder = connect_test_database(test_db.info.dbname)
    try:
        holder.execute(
            "SELECT id FROM qa_plan_executions WHERE id=%s FOR UPDATE",
            (str(execution["id"]),),
        )
        started = monotonic()
        response = dispatch(
            FunctionCallRequest(
                function="qa.plan_execution.pause",
                actor=ActorContext(
                    actor_id=str(execution["actor_id"]), session_id=SESSION
                ),
                target=TargetRef(
                    kind="deployment_run", deployment_run_id=run_id, project_id="yoke"
                ),
                payload={
                    "execution_id": str(execution["id"]),
                    "phase": "checkin",
                    "cursor": 0,
                    "request_id": "pause-behind-lock",
                    "attempts": [],
                },
            )
        )
        waited = monotonic() - started
    finally:
        holder.rollback()
        holder.close()

    assert not response.success
    assert response.error.code == "plan_execution_invalid"
    assert response.error.message.startswith("qa_checkin_busy:")
    assert "retry the same execution" in response.error.message
    assert waited < 10
    state, reason = test_db.execute(
        "SELECT state,release_reason FROM qa_plan_executions WHERE id=%s",
        (str(execution["id"]),),
    ).fetchone()
    assert state == execution["state"]
    assert not str(reason or "").startswith(PAUSE_REASON)
