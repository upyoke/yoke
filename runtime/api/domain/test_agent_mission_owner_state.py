"""The control plane answers whether a host marker's owner execution finished."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.test_agent_mission_qa import (
    ACTOR,
    _materialize_mission,
    _request,
)
from yoke_core.domain.agent_mission_owner_state import (
    handle_agent_mission_owner_state,
)
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def _owner_state(item_id: int, execution_id: str, owner: str) -> Any:
    request = _request(
        "test_machine.mission.owner_state",
        item_id=item_id,
        execution_id=execution_id,
        requirement_id=1,
        payload={"owner_execution_id": owner},
    )
    request.payload.pop("requirement_id")
    return handle_agent_mission_owner_state(request)


def test_owner_state_reports_live_unknown_and_terminal_owners(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4551
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])

    unleased = _owner_state(item_id, execution_id, execution_id)
    assert not unleased.primary_success
    assert unleased.error.code == "agent_mission_owner_state_failed"

    begun = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
        )
    )
    assert begun.primary_success, begun.error

    live = _owner_state(item_id, execution_id, execution_id)
    assert live.primary_success, live.error
    assert live.result_payload["terminal"] is False
    assert live.result_payload["state"] not in {"completed", "aborted", "error"}

    unknown = _owner_state(item_id, execution_id, "never-issued")
    assert unknown.result_payload == {
        "execution_id": execution_id,
        "owner_execution_id": "never-issued",
        "state": None,
        "terminal": False,
    }

    test_db.execute(
        "UPDATE qa_plan_executions SET state='completed' WHERE id=%s",
        (execution_id,),
    )
    test_db.commit()
    finished = _owner_state(item_id, execution_id, execution_id)
    assert finished.result_payload["state"] == "completed"
    assert finished.result_payload["terminal"] is True
