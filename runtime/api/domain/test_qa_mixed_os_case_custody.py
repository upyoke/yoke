"""A plan can admit two walks and route each one to its own retained host."""

import pytest

from runtime.api.domain.agent_mission_qa_test_support import ACTOR
from runtime.api.domain.deployment_qa_stage_execution_test_support import _environment
from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
    verify_fixture_host,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_contracts.machine_config.capability_secret_store import store_test_machine_secret
from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)
from yoke_core.domain.handlers.machine_qa_case import handle_case_begin
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_local_execution import prepare_agent_mission_contract
from yoke_core.domain.machine_qa_mission_walk import (
    execute_agent_mission_walk_end,
    execute_agent_mission_walk_start,
)
from yoke_core.domain.qa_plan_chain_hosts import chain_host_groups
from yoke_core.domain.qa_host_set_turns import execution_waits
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import advance_plan_execution
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution

WINDOWS = "windows-lab"
ARM_MAC = "mac-studio-lab"


@pytest.fixture
def registered_hosts(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    for name, platform, tags in (
        (WINDOWS, "windows", ""),
        (ARM_MAC, "macos", "arch:arm64"),
    ):
        replace_test_machine_settings(
            test_db, test_machine=name, power_project="yoke", base_settings=None,
            settings={
                **TEST_MACHINE_SETTINGS, "resource_name": name, "os": platform,
                **({"capability_tags": tags} if tags else {}),
            },
        )
        store_test_machine_secret(name, "ssh_private_key", "fixture-key")
        verify_fixture_host(test_db, name)
    _environment(test_db)


def _create_plan(conn, slug, platforms, *, method="exploratory-mission"):
    plan = create_plan(conn, project="yoke", slug=slug, target_environment="stage")
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": platform,
                "method_id": method,
                "instructions": "Check the host selected for this case.",
                "expected_outcome": "The case uses its declared platform.",
                "method_config": {
                    **({"executor": "informed_subagent"} if method == "exploratory-mission"
                       else {"assertions": [{"argv": ["/usr/bin/true"]}]}),
                    "os": platform,
                    **({"capability_tags": ["arch:arm64"]} if platform == "macos" else {}),
                },
                "host_baselines": ["fresh-host"],
            }
            for platform in platforms
        ],
    )


@pytest.fixture
def mixed_missions(test_db, registered_hosts):
    _create_plan(test_db, "mixed-os-walk", ("windows", "macos"))
    execution = begin_standalone_execution(
        test_db, plan="mixed-os-walk", project="yoke",
        actor_id=ACTOR.actor_id, session_id=ACTOR.session_id,
    )
    def factory(material):
        control = FakeHostControl()
        control.test_machine = material.settings["resource_name"]
        return control

    register_host_control_factory(factory)
    try:
        yield execution
    finally:
        clear_host_control_factory()


def _request(execution, index, function, *, actor=ACTOR, **payload):
    return FunctionCallRequest(
        function=function,
        actor=actor,
        target=TargetRef(kind="global", project_id="yoke"),
        payload={
            "execution_id": execution["id"],
            "requirement_id": execution["roster"][index]["requirement_id"],
            **payload,
        },
    )


def test_walk_start_and_end_keep_each_cases_original_lease(test_db, mixed_missions):
    execution = mixed_missions
    original = {}
    for ordinal, host in enumerate((WINDOWS, ARM_MAC)):
        begun = handle_plan_case_begin(
            _request(execution, ordinal, "test_machine.plan_case.begin", ordinal=ordinal)
        )
        assert begun.primary_success, begun.error
        contract = begun.result_payload["execution"]
        assert contract["settings"]["resource_name"] == host
        original[host] = contract["lease_id"]
        prepared = prepare_agent_mission_contract(contract)
        ready = handle_agent_mission_ready(
            _request(execution, ordinal, "test_machine.mission.ready", ordinal=ordinal, **prepared)
        )
        assert ready.primary_success, ready.error
    assert {str(claim.target.test_machine): claim.id
            for claim in execution_host_leases(test_db, execution)} == original

    current = lock_plan_execution(test_db, execution["id"])
    begin_plan_review(test_db, current)
    for ordinal, host in enumerate((WINDOWS, ARM_MAC)):
        start = handle_agent_mission_access(
            _request(execution, ordinal, "test_machine.mission.access")
        )
        assert start.primary_success, start.error
        contract = start.result_payload["execution"]
        assert contract["lease_id"] == original[host]
        assert contract["settings"]["resource_name"] == host
        assert execute_agent_mission_walk_start(contract)["preparation"]["ok"]

        end = handle_agent_mission_access(
            _request(
                execution, ordinal, "test_machine.mission.access",
                cleanup="begin", run_id=start.result_payload["run_id"],
            )
        )
        assert end.primary_success, end.error
        contract = end.result_payload["execution"]
        assert contract["lease_id"] == original[host]
        result = execute_agent_mission_walk_end(contract)
        assert contract["settings"]["resource_name"] == host
        assert result["starting_state_restore"]["restored"]


def test_os_only_cases_and_slots_have_distinct_partition_keys():
    def case(requirement_id, config):
        return {
            "requirement_id": requirement_id,
            "runner_id": "agent_mission",
            "method_config": config,
            "starting_state": "baseline",
        }

    roster = [
        case(1, {"os": "windows"}),
        case(2, {"os": "macos"}),
        case(3, {"test_machines": [{"os": "windows"}, {"os": "macos", "driver": True}]}),
        case(4, {"os": "macos"}),
    ]
    groups = chain_host_groups(roster)
    assert len({groups[1], groups[2], groups[3]}) == 3
    assert groups[2] == groups[4]



def test_opposite_case_orders_wait_for_the_same_complete_set(test_db, mixed_missions):
    first = mixed_missions
    second_actor = ACTOR.model_copy(update={"session_id": "second-mixed-walk"})
    seed_qa_session(test_db, second_actor.session_id, messageable=True)
    _create_plan(test_db, "mac-before-windows", ("macos", "windows"))
    second = begin_standalone_execution(
        test_db, plan="mac-before-windows", project="yoke",
        actor_id=second_actor.actor_id, session_id=second_actor.session_id,
    )
    first_begin = handle_plan_case_begin(
        _request(first, 0, "test_machine.plan_case.begin", ordinal=0)
    )
    assert first_begin.primary_success, first_begin.error
    request = _request(
        second, 0, "test_machine.plan_case.begin", ordinal=0, actor=second_actor
    )
    waiting = handle_plan_case_begin(request)
    assert waiting.primary_success, waiting.error
    assert waiting.result_payload["state"] == "waiting"
    assert not execution_host_leases(test_db, second)
    waits = execution_waits(test_db, second["id"])
    assert {row["test_machine"] for row in waits} == {WINDOWS, ARM_MAC}
    assert len({row["queued_at"] for row in waits}) == 1
    assert {row["state"] for row in waits} == {"waiting"}

    current = lock_plan_execution(test_db, first["id"])
    for ordinal, case in enumerate(current["roster"]):
        requirement_id = case["requirement_id"]
        advance_plan_execution(
            test_db, current, ordinal=ordinal, requirement_id=requirement_id,
            result={"requirement_id": requirement_id, "case_outcome": "passed"},
            commit=False,
        )
    finish_plan_execution(test_db, current, state="completed", reason="first walk completed")
    begin_standalone_execution(
        test_db, plan="mac-before-windows", project="yoke",
        actor_id=second_actor.actor_id, session_id=second_actor.session_id,
    )
    ready = handle_plan_case_begin(request)
    assert ready.primary_success, ready.error
    assert ready.result_payload["state"] == "ready"
    assert ready.result_payload["execution"]["settings"]["resource_name"] == ARM_MAC
    assert {lease.target.test_machine for lease in execution_host_leases(test_db, second)} == {
        WINDOWS, ARM_MAC,
    }


@pytest.mark.parametrize(
    ("host", "error"),
    [(ARM_MAC, None), (WINDOWS, "test_machine_platform_unavailable"),
     (TEST_MACHINE_SETTINGS["resource_name"], "test_machine_capability_tags_unavailable")],
)
def test_direct_case_pin_checks_platform_and_tags(test_db, registered_hosts, host, error):
    _create_plan(test_db, "one-arm-mac-case", ("macos",), method="machine-state-check")
    execution = begin_standalone_execution(
        test_db, plan="one-arm-mac-case", project="yoke",
        actor_id=ACTOR.actor_id, session_id=ACTOR.session_id,
    )
    result = handle_case_begin(FunctionCallRequest(
        function="test_machine.case.begin",
        actor=ACTOR,
        target=TargetRef(kind="qa_requirement", qa_requirement_id=execution["roster"][0]["requirement_id"]),
        payload={"test_machine": host},
    ))
    if error:
        assert not result.primary_success
        assert error in result.error.message
    else:
        assert result.primary_success, result.error
        assert result.result_payload["execution"]["settings"]["resource_name"] == host
