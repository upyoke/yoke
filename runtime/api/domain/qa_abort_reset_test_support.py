# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from datetime import timedelta

import pytest

from runtime.api.domain.machine_qa_plan_execution_test_support import (
    ACTOR,
    _request,
    _active_lease_count,
)

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_contracts.timestamps import utc_now

from yoke_core.domain.handlers.machine_qa_plan_case import (
    handle_plan_case_begin,
    handle_plan_case_submit,
)

from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
    heartbeat_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

from yoke_core.domain.qa_plan_execution_abort_state import (
    abort_request,
    host_cleanup_proven,
)


def operation(actor, operation="reset", **payload):
    return FunctionCallRequest(
        function="test_machine.operation.begin",
        actor=actor,
        target=TargetRef(kind="global"),
        payload={
            "project": "yoke",
            "operation": operation,
            "baseline": "fresh-host",
            **payload,
        },
    )


@pytest.fixture
def failed_restore(test_db, tmp_path, monkeypatch):
    item_id = 4550
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    heartbeat_plan_execution(test_db, execution)
    assert "case_inflight" not in json.loads(
        execution["release_reason"].split(":", 1)[1]
    )
    case = execution["roster"][0]
    ready = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution["id"],
            ordinal=0,
            requirement_id=case["requirement_id"],
        )
    )
    assert ready.primary_success, ready.error
    issued = ready.result_payload["execution"]
    current = lock_plan_execution(test_db, execution["id"])
    assert "case_inflight" not in json.loads(current["release_reason"].split(":", 1)[1])
    heartbeat_plan_execution(test_db, current)
    assert json.loads(current["release_reason"].split(":", 1)[1])["case_inflight"] == 0
    with pytest.raises(QaPlanExecutionStateError, match="qa_pause_unconfirmed"):
        begin_plan_execution(
            test_db,
            item_id=item_id,
            transition_id="reviewing-implementation",
            actor_id=ACTOR.actor_id,
            session_id=ACTOR.session_id,
        )
    submitted = handle_plan_case_submit(
        _request(
            "test_machine.plan_case.submit",
            item_id=item_id,
            execution_id=execution["id"],
            ordinal=0,
            requirement_id=case["requirement_id"],
            payload={
                "lease_id": issued["lease_id"],
                "contract_digest": issued["contract_digest"],
                "results": [
                    {
                        "requirement_id": case["requirement_id"],
                        "case_outcome": "failed",
                        "verdict": "fail",
                        "duration_ms": 1,
                        "error_code": "test_mac_reset_script_cleanup_failed",
                        "evidence": {
                            "runner_id": "host_control",
                            "test_machine": "mac-mini-lab",
                            "method_id": case["method_id"],
                            "baseline": case["host_baseline"],
                            "starting_state_restore": {
                                "baseline": case["host_baseline"],
                                "restored": False,
                            },
                        },
                    }
                ],
            },
        )
    )
    assert submitted.primary_success, submitted.error
    current = lock_plan_execution(test_db, execution["id"])
    heartbeat_plan_execution(test_db, current)
    # Advancing the cursor and renewing liveness must not invent a new start.
    assert json.loads(current["release_reason"].split(":", 1)[1])["case_inflight"] == 0
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_restore_pending"):
        finish_plan_execution(
            test_db, current, state="aborted", reason="stop failed runner"
        )
    assert abort_request(current)["requested_at"]
    return current
