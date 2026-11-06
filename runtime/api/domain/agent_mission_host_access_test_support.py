# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import subprocess

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)

from runtime.api.domain.machine_qa_test_support import FakeHostControl

from runtime.api.domain.agent_mission_qa_test_support import ACTOR, _request

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)

from yoke_core.domain.coordination_claims import release

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)

from yoke_core.domain.machine_qa_capability import replace_test_machine_settings

from yoke_core.domain.machine_qa_local_execution import (
    execute_agent_mission_host_command,
    prepare_agent_mission_contract,
)

from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_host_leases import execution_host_leases

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_review import begin_plan_review

DRIVER = TEST_MACHINE_SETTINGS["resource_name"]

COMPANION = "companion-lab"

ITEM = 7851


@pytest.fixture
def mission(test_db, tmp_path, monkeypatch, request):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    replace_test_machine_settings(
        test_db,
        project="yoke",
        test_machine=COMPANION,
        settings={**TEST_MACHINE_SETTINGS, "resource_name": COMPANION},
        base_settings=None,
    )
    plan = create_plan(test_db, project="yoke", slug="companion-host-mission")
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "two-host-walk",
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": "Command both declared hosts.",
                "expected_outcome": "Both commands use their own leases.",
                "method_config": {
                    "executor": "informed_subagent",
                    "test_machine": DRIVER,
                    "test_machines": [DRIVER, COMPANION],
                },
                **(
                    {
                        "starting_state": "as_is",
                        "starting_state_reason": "Preserve host",
                    }
                    if getattr(request, "param", None) == "as_is"
                    else {"host_baselines": ["fresh-host"]}
                ),
            }
        ],
    )
    insert_item(
        test_db,
        id=ITEM,
        title="Walk both hosts",
        workflow_id="issue",
        status="implementing",
    )
    attach_plan_to_item(
        test_db,
        plan_id=int(plan["id"]),
        item_id=ITEM,
        transition_id="reviewing-implementation",
    )
    materialized = materialize_for_item(
        test_db, item_id=ITEM, transition_id="reviewing-implementation"
    )
    requirement = int(materialized["created_requirement_ids"][0])
    execution = begin_plan_execution(
        test_db,
        item_id=ITEM,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    request = _request(
        "test_machine.plan_case.begin",
        item_id=ITEM,
        execution_id=execution["id"],
        requirement_id=requirement,
        ordinal=0,
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(begun.result_payload["execution"])
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        request.model_copy(
            update={
                "function": "test_machine.mission.ready",
                "payload": {**request.payload, **prepared},
            }
        )
    )
    assert ready.primary_success, ready.error
    current = lock_plan_execution(test_db, execution["id"])
    begin_plan_review(test_db, current)
    return request.model_copy(
        update={
            "function": "test_machine.mission.access",
            "payload": {"execution_id": execution["id"], "requirement_id": requirement},
        }
    ), current
