# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)

from runtime.api.domain.machine_qa_test_support import FakeHostControl

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    _materialize_mission,
    _request,
)

from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef

from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.handlers.qa_plan_review import (
    handle_plan_review_begin,
    handle_plan_review_submit,
)

from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)

from yoke_core.domain.machine_qa_local_execution import (
    prepare_agent_mission_contract,
)

from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)


def _recorded_mission(test_db: Any, tmp_path: Any, monkeypatch: Any, item_id: int):
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
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(begun.result_payload["execution"])
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload=prepared,
        )
    )
    assert ready.primary_success, ready.error
    return requirement_id, execution_id, int(ready.result_payload["result"]["run_id"])
