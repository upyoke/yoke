"""Host-action safety at the QA mission-continuation boundary."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_operation_test_support import operation_receipts
from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_qa import _materialize_mission
from runtime.api.domain.test_qa_plan_execution_parked_continuation import (
    LONG_AGO,
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
    PRE_HOST_ERROR_REASON,
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
            reason=PRE_HOST_ERROR_REASON,
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


def test_fresh_mission_resets_for_its_docket_and_again_at_walk_start(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    from yoke_core.domain.machine_qa_mission_walk import (
        execute_agent_mission_walk_start,
    )

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
    begun = handle_plan_case_begin(_request(item_id, execution))
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    assert contract["baselines"] == ["fresh-host"]

    register_host_control_factory(lambda _material: control)
    try:
        prepared = prepare_agent_mission_contract(contract)
        # The docket's receipt proves the declared baseline.
        assert control.full_reset_calls == 1
        assert SENTINEL not in control.existing_paths
        assert prepared["preparation"]["baseline"] == "fresh-host"
        ready = handle_agent_mission_ready(
            _request(item_id, execution, payload=prepared)
        )
        assert ready.primary_success, ready.error
        # Later plan cases may change the machine before the walk begins,
        # so walk-start reaches the baseline again.
        control.existing_paths.add(SENTINEL)
        started = execute_agent_mission_walk_start(contract)
    finally:
        clear_host_control_factory()

    assert control.full_reset_calls == 2
    assert SENTINEL not in control.existing_paths
    assert started["preparation"]["baseline"] == "fresh-host"
    assert started["preparation"]["ok"] is True


def test_a_continuation_leaves_the_prior_settled_run_as_history(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    requirement_id, settled = _swept_mission(
        test_db, tmp_path, monkeypatch, item_id=4907
    )
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "verdict_reason,execution_status,case_outcome,started_at,completed_at,"
        "created_at) VALUES(%s,'agent_mission','plan_case','error',"
        "'settled by execution termination','captured','needs_review',"
        "%s,%s,%s)",
        (requirement_id, LONG_AGO, LONG_AGO, LONG_AGO),
    )
    test_db.commit()

    begin_plan_execution(
        test_db,
        item_id=4907,
        transition_id=MISSION_TRANSITION,
        continue_mission=True,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    prior_runs = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs WHERE qa_requirement_id=%s",
        (requirement_id,),
    ).fetchall()
    assert [(str(row[0]), str(row[1])) for row in prior_runs] == [
        ("error", "settled by execution termination")
    ]
    assert str(settled["release_reason"]) == "stale-heartbeat"
