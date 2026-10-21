"""Refusals that strand an execution name steering reconciliation exactly."""

import pytest

from runtime.api.domain.test_agent_mission_cleanup import removed_mission  # noqa: F401
from runtime.api.domain.test_agent_mission_qa import ACTOR
from runtime.api.domain.test_qa_plan_execution_adoption import _adopt, _setup
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.qa_plan_execution_checkin import restore_confirmed_pause
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
)


def _command(execution_id, project="yoke"):
    return f"yoke qa plan reconcile --project {project} --execution-id {execution_id}"


def test_invalid_recovery_receipt_names_reconcile(tmp_path):
    with pytest.raises(QaPlanExecutionError) as refused:
        restore_confirmed_pause(
            str(tmp_path / "missing-receipt.json"),
            call=None,
            target=TargetRef(kind="item", public_ref="YOK-1"),
            actor=None,
            execution_id="execution-1",
            project="yoke",
        )
    assert "qa_recovery_receipt_invalid" in str(refused.value)
    assert _command("execution-1") in str(refused.value)


def test_walk_end_refusal_names_reconcile_only_when_owner_ended(
    removed_mission,  # noqa: F811
    test_db,
):
    request, _, _original = removed_mission
    execution_id = request.payload["execution_id"]
    register_session_actor(test_db, ACTOR.session_id)
    execution = lock_plan_execution(test_db, execution_id)
    with pytest.raises(QaPlanExecutionStateError) as live:
        finish_plan_execution(test_db, execution, state="aborted", reason="operator")
    test_db.rollback()
    assert "qa_abort_walk_end_required" in str(live.value)
    assert "yoke qa plan reconcile" not in str(live.value)

    test_db.execute(
        "UPDATE harness_sessions SET ended_at=CURRENT_TIMESTAMP WHERE session_id=%s",
        (ACTOR.session_id,),
    )
    test_db.commit()
    execution = lock_plan_execution(test_db, execution_id)
    with pytest.raises(QaPlanExecutionStateError) as ended:
        finish_plan_execution(test_db, execution, state="aborted", reason="operator")
    test_db.rollback()
    assert "qa_abort_walk_end_required" in str(ended.value)
    assert _command(execution_id) in str(ended.value)


def test_unprovable_predecessor_adoption_names_reconcile():
    with test_database() as conn:
        execution, _requirement, _capture, actor = _setup(conn)
        conn.execute(
            "UPDATE qa_plan_executions SET session_id='unregistered-predecessor' "
            "WHERE id=%s",
            (execution["id"],),
        )
        conn.commit()
        with pytest.raises(ValueError) as refused:
            _adopt(conn, execution, actor)
        assert "qa_adoption_owner_unverified" in str(refused.value)
        assert _command(execution["id"]) in str(refused.value)
