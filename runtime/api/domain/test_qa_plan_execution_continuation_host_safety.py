"""Host-action safety at the QA mission-continuation boundary."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_operation_test_support import operation_receipts
from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_qa import _materialize_mission
from runtime.api.domain.test_qa_plan_execution_parked_continuation import (
    MISSION_ACTOR,
    MISSION_TRANSITION,
    _swept_mission,
)
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    prepare_agent_mission_contract,
)
from yoke_core.domain.qa_plan_execution_continuation import (
    CONTINUATION_PRE_HOST_ERROR_REASON,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
)

SENTINEL = "/Users/tester/code/partial-walk/sentinel.txt"


def _request(
    item_id: int,
    execution: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="test_machine.plan_case.begin",
        actor=MISSION_ACTOR,
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "execution_id": str(execution["id"]),
            "ordinal": 0,
            "requirement_id": int(execution["roster"][0]["requirement_id"]),
            **(payload or {}),
        },
    )


def _prepare(
    item_id: int,
    execution: dict[str, Any],
    control: FakeHostControl,
) -> tuple[dict[str, Any], FunctionCallRequest]:
    begun = handle_plan_case_begin(_request(item_id, execution))
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    register_host_control_factory(lambda _material: control)
    try:
        prepared = prepare_agent_mission_contract(contract)
    finally:
        clear_host_control_factory()
    return prepared, _request(item_id, execution, payload=prepared)


@pytest.mark.parametrize("recover_pre_host", [False, True])
def test_continuation_preparation_preserves_populated_host_state(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
    recover_pre_host: bool,
) -> None:
    item_id = 4910
    _requirement_id, settled = _swept_mission(
        test_db, tmp_path, monkeypatch, item_id=item_id
    )
    if recover_pre_host:
        failed = begin_plan_execution(
            test_db,
            item_id=item_id,
            transition_id=MISSION_TRANSITION,
            continue_mission=True,
            actor_id=MISSION_ACTOR.actor_id,
            session_id=MISSION_ACTOR.session_id,
        )
        finish_plan_execution(
            test_db,
            failed,
            state="aborted",
            reason=CONTINUATION_PRE_HOST_ERROR_REASON,
        )
    continued = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id=MISSION_TRANSITION,
        continue_mission=True,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    assert continued["continues_execution_id"] == settled["id"]
    control = FakeHostControl()
    control.existing_paths.add(SENTINEL)

    prepared, ready_request = _prepare(item_id, continued, control)

    assert control.full_reset_calls == 0
    assert SENTINEL in control.existing_paths
    assert prepared["preparation"]["baseline"] is None
    ready = handle_agent_mission_ready(ready_request)
    assert ready.primary_success, ready.error
    assert operation_receipts(test_db) == []


def test_fresh_mission_preparation_resets_and_records_its_receipt(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4911
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id=MISSION_TRANSITION,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    control = FakeHostControl()
    control.existing_paths.add(SENTINEL)

    prepared, ready_request = _prepare(item_id, execution, control)

    assert control.full_reset_calls == 1
    assert SENTINEL not in control.existing_paths
    ready = handle_agent_mission_ready(ready_request)
    assert ready.primary_success, ready.error
    [receipt] = operation_receipts(test_db)
    assert receipt["operation"] == "reset"
    assert receipt["status"] == "verified"
    assert receipt["checks"][0]["name"] == "fresh-host"
