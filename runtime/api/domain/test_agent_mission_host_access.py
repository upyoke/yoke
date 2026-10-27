"""Mission commands select only their case's retained driver and companions."""

import subprocess

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_qa import ACTOR, _request
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
                    {"starting_state": "as_is", "starting_state_reason": "Preserve host"}
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


@pytest.mark.parametrize("test_machine", [None, DRIVER, COMPANION])
def test_command_routes_to_selected_retained_lease(test_db, mission, test_machine):
    request, execution = mission
    if test_machine is not None:
        request = request.model_copy(
            update={"payload": {**request.payload, "test_machine": test_machine}}
        )
    outcome = handle_agent_mission_access(request)
    assert outcome.primary_success, outcome.error
    contract = outcome.result_payload["execution"]
    selected = test_machine or DRIVER
    leases = execution_host_leases(test_db, execution)
    lease = next(claim for claim in leases if claim.target.test_machine == selected)
    assert contract["lease_id"] == lease.id
    assert contract["settings"]["resource_name"] == selected
    assert execution["test_machine_lease_id"] == next(
        claim.id for claim in leases if claim.target.test_machine == DRIVER
    )
    assert contract["operation"] == (
        "host_command" if selected == COMPANION else "plan_case"
    )
    if selected == COMPANION:
        assert not contract["cases"] and not contract["baselines"]
        assert contract["plan_execution_id"] is None
    controls = []

    class CommandControl(FakeHostControl):
        def run_command(self, argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, selected, "")

    def factory(material):
        controls.append(material)
        return CommandControl()

    register_host_control_factory(factory)
    try:
        result = execute_agent_mission_host_command(
            contract,
            argv=["hostname"],
            gui_session=False,
            timeout_seconds=60,
        )
    finally:
        clear_host_control_factory()
    assert result["exit_code"] == 0
    assert result["stdout"] == selected
    assert controls
    assert all(claim.is_active for claim in execution_host_leases(test_db, execution))


def test_outside_host_is_refused_by_name_before_local_execution(mission):
    request, _ = mission
    outcome = handle_agent_mission_access(
        request.model_copy(
            update={
                "payload": {**request.payload, "test_machine": "unleased-lab"},
            }
        )
    )
    assert not outcome.primary_success
    assert "mission_machine_not_declared" in outcome.error.message
    assert "unleased-lab" in outcome.error.message
    assert "omit --test-machine" in outcome.error.message
    assert COMPANION in outcome.error.message


def test_companion_command_refuses_after_another_host_lease_is_lost(test_db, mission):
    request, execution = mission
    driver = next(
        claim
        for claim in execution_host_leases(test_db, execution)
        if claim.target.test_machine == DRIVER
    )
    release(test_db, driver.id, "forced-recovery")
    outcome = handle_agent_mission_access(
        request.model_copy(
            update={
                "payload": {**request.payload, "test_machine": COMPANION},
            }
        )
    )
    assert not outcome.primary_success
    assert "test_machine_set_lease_lost" in outcome.error.message


@pytest.mark.parametrize("command_exit", [0, 1])
def test_companion_debt_survives_driver_walk_end_and_host_release(
    test_db,
    mission,
    command_exit,
):
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.machine_reset_debt import reset_owed
    from yoke_core.domain.machine_qa_mission_walk import execute_agent_mission_walk_end
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    request, execution = mission
    leases = execution_host_leases(test_db, execution)
    assert reset_owed(test_db, COMPANION) is None
    outcome = handle_agent_mission_access(
        request.model_copy(
            update={
                "payload": {**request.payload, "test_machine": COMPANION},
            }
        )
    )
    assert outcome.primary_success, outcome.error
    contract = outcome.result_payload["execution"]
    # Releasing a caller transaction cannot undo debt already committed with
    # the access receipt, before the command is sent to the physical host.
    test_db.rollback()
    assert reset_owed(test_db, COMPANION) == "fresh-host"

    class CommandControl(FakeHostControl):
        def run_command(self, argv, **kwargs):
            return subprocess.CompletedProcess(argv, command_exit, "", "")

    register_host_control_factory(lambda material: CommandControl())
    try:
        result = execute_agent_mission_host_command(
            contract,
            argv=["mutate-host"],
            gui_session=False,
            timeout_seconds=60,
        )
    finally:
        clear_host_control_factory()
    assert result["exit_code"] == command_exit
    driver = handle_agent_mission_access(request)
    assert driver.primary_success, driver.error
    register_host_control_factory(lambda material: FakeHostControl())
    try:
        ended = execute_agent_mission_walk_end(driver.result_payload["execution"])
    finally:
        clear_host_control_factory()
    assert ended["removed"]
    assert ended["starting_state_restore"]["restored"]
    finish_plan_execution(test_db, execution, state="completed", reason="walk-finished")
    assert all(not get_claim(test_db, claim.id).is_active for claim in leases)
    assert reset_owed(test_db, COMPANION) == "fresh-host"
    assert reset_owed(test_db, DRIVER) is None


def test_driver_access_does_not_mark_an_untouched_companion_dirty(test_db, mission):
    from yoke_core.domain.machine_reset_debt import reset_owed

    request, _ = mission
    outcome = handle_agent_mission_access(request)
    assert outcome.primary_success, outcome.error
    assert reset_owed(test_db, COMPANION) is None


@pytest.mark.parametrize("mission", ["as_is"], indirect=True)
def test_as_is_companion_access_owes_the_hosts_last_verified_baseline(
    test_db, mission
):
    from runtime.api.domain.test_machine_reset_debt import verified_reset
    from yoke_core.domain.machine_reset_debt import reset_owed
    from yoke_core.domain.machine_qa_mission_walk import execute_agent_mission_walk_end

    request, _ = mission
    companion = request.model_copy(
        update={"payload": {**request.payload, "test_machine": COMPANION}}
    )
    outcome = handle_agent_mission_access(companion)
    assert outcome.primary_success, outcome.error
    test_db.rollback()
    assert reset_owed(test_db, COMPANION) is None  # Never verified clean.
    verified_reset(test_db, COMPANION, "fresh-host")
    outcome = handle_agent_mission_access(companion)  # Owned cleanup, same path.
    assert outcome.primary_success, outcome.error
    test_db.rollback()
    assert reset_owed(test_db, COMPANION) == "fresh-host"
    driver = handle_agent_mission_access(request)
    assert driver.primary_success, driver.error
    register_host_control_factory(lambda material: FakeHostControl())
    try:
        ended = execute_agent_mission_walk_end(driver.result_payload["execution"])
    finally:
        clear_host_control_factory()
    assert ended["removed"]
    assert ended["starting_state_restore"]["restored"] is False
    assert "error_code" not in ended["starting_state_restore"]
    assert reset_owed(test_db, COMPANION) == "fresh-host"
