"""Controller mission capture never charges reset debt to a preceding clean host."""

import pytest

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_agent_mission_controller import _mission
from runtime.api.domain.test_machine_qa_plan_execution import _execute_begin_contract
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.machine_qa_plan_case import (
    handle_plan_case_begin,
    handle_plan_case_submit,
)
from yoke_core.domain.qa_plan_execution_state import (
    lock_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review


@pytest.mark.parametrize("abort", [True, False])
def test_controller_after_clean_host_leaves_receipts_unchanged(
    test_db, tmp_path, monkeypatch, abort
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "manual-owner", actor_id=7)
    execution = _mission(test_db, with_host=True)

    def request(ordinal, function="test_machine.plan_case.begin", payload=None):
        return FunctionCallRequest(
            function=function,
            actor=ActorContext(actor_id="7", session_id="manual-owner"),
            target=TargetRef(kind="global", project_id="yoke"),
            payload={
                "execution_id": execution["id"],
                "ordinal": ordinal,
                "requirement_id": execution["roster"][ordinal]["requirement_id"],
                **(payload or {}),
            },
        )

    begun = handle_plan_case_begin(request(0))
    submission = _execute_begin_contract(begun)
    try:
        submitted = handle_plan_case_submit(
            request(0, "test_machine.plan_case.submit", submission.payload)
        )
        assert submitted.primary_success, submitted.error
    finally:
        submission.cleanup_artifacts()

    def receipts():
        return test_db.execute(
            "SELECT capability_type,operation,receipt_json FROM test_machine_operation_receipts ORDER BY capability_type,operation"
        ).fetchall()

    before = receipts()
    captured = handle_plan_case_begin(request(1))
    assert captured.primary_success, captured.error
    execution = lock_plan_execution(test_db, execution["id"])
    if abort:
        finish_plan_execution(
            test_db, execution, state="aborted", reason="controller stop"
        )
    else:
        assert begin_plan_review(test_db, execution)
        execution = lock_plan_execution(test_db, execution["id"])
        assert execution["state"] == "awaiting_walk_review"
    assert execution["test_machine_lease_id"] is None
    assert receipts() == before
    assert all(row[1] != "reset_owed" for row in before)
