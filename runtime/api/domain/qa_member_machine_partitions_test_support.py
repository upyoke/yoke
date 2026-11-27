# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    _terminal_recipe,
    configure_test_machine,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _seed_run,
    _stages,
)

from yoke_core.domain.coordination_claims import acquire, release

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.machine_qa_capability import replace_test_machine_settings

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.work_claim_targets import make_qa_admission_target

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

MACHINES = ("mac-mini-lab", "mac-studio-lab")

#: Each fixture host is the only one of its OS, so an OS selects it.
OSES = {MACHINES[0]: "macos", MACHINES[1]: "linux"}

RUN = "run-member-hosts"

MEMBER = 9820

SESSION = "session-machine-plan"


def register_second_host(conn):
    """Register and verify MACHINES[1], the fleet's one linux host."""
    from runtime.api.domain.machine_qa_host_test_support import verify_fixture_host

    replace_test_machine_settings(
        conn,
        power_project="yoke",
        test_machine=MACHINES[1],
        settings={
            **TEST_MACHINE_SETTINGS, "resource_name": MACHINES[1], "os": OSES[MACHINES[1]],
        },
        base_settings=None,
    )
    verify_fixture_host(conn, MACHINES[1])


def host_slots(driver=None):
    """One OS slot per fixture host, the driver's OS marked."""
    return [
        {"os": OSES[name], **({"driver": True} if name == (driver or MACHINES[0]) else {})}
        for name in MACHINES
    ]


def _seed(
    conn,
    tmp_path,
    monkeypatch,
    *,
    simultaneous=False,
    driver=None,
    inherit=False,
    mission=False,
    trailing=False,
    run_scope=False,
):
    configure_test_machine(conn, tmp_path, monkeypatch)
    seed_registered_qa_launch(conn, SESSION)
    register_second_host(conn)
    plan = create_plan(
        conn,
        project="yoke",
        slug="host-check-0",
        infer_target_environment=False,
    )
    machines = [driver or MACHINES[0]] if simultaneous else list(MACHINES)
    if trailing:
        machines = [*machines, "independent"]

    def hosts(key, position):
        if simultaneous or (inherit and position <= 2):
            return {"test_machines": host_slots(driver)}
        return {"os": OSES.get(key, OSES[MACHINES[0]])}

    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "exploratory-mission"
                if mission and position == 2
                else "terminal-check",
                "instructions": "Run a host-specific check.",
                "expected_outcome": "The check passes.",
                "method_config": {
                    **({} if mission and position == 2 else _terminal_recipe()),
                    **hosts(key, position),
                    **(
                        {"executor": "informed_subagent"}
                        if mission and position == 2
                        else {}
                    ),
                },
                "entry_surface": "printf done",
                "required_completion": "complete",
                "starting_state": "inherit" if inherit and position == 2 else "baseline",
                "host_baselines": [] if inherit and position == 2 else ["fresh-host"],
            }
            for position, key in enumerate(machines, 1)
        ],
    )
    _materialize(conn, int(plan["id"]), machines, run_scope=run_scope)


def seed_fleet_cases(conn, tmp_path, monkeypatch, fleet, cases):
    """Register *fleet* ({name: os}, verified) beside the fixture mac and
    materialize *cases* (terminal checks keyed by case_key) for MEMBER."""
    from runtime.api.domain.machine_qa_host_test_support import verify_fixture_host

    configure_test_machine(conn, tmp_path, monkeypatch)
    for name, os_name in fleet.items():
        replace_test_machine_settings(
            conn,
            power_project="yoke",
            test_machine=name,
            settings={**TEST_MACHINE_SETTINGS, "resource_name": name, "os": os_name},
            base_settings=None,
        )
        verify_fixture_host(conn, name)
    plan = create_plan(conn, project="yoke", slug="host-check-0", infer_target_environment=False)
    inherit = {"starting_state": "inherit", "host_baselines": []}
    baseline = {"starting_state": "baseline", "host_baselines": ["fresh-host"]}
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": case["case_key"],
                "position": position,
                "method_id": "terminal-check",
                "instructions": "Run a host-specific check.",
                "expected_outcome": "The check passes.",
                "method_config": {**_terminal_recipe(), **case.get("hosts", {})},
                "entry_surface": "printf done",
                "required_completion": "complete",
                **(inherit if case.get("inherit") else baseline),
            }
            for position, case in enumerate(cases, 1)
        ],
    )
    _materialize(conn, int(plan["id"]), [case["case_key"] for case in cases])


def _materialize(conn, plan_id, case_keys, *, run_scope=False):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        conn, id=MEMBER, project_sequence=MEMBER, workflow_id="issue", status="done"
    )
    # The flow pins the plan's cases to the stage, so each member walks its own
    # copy; an attached post-deploy plan would run as a memberless plan group.
    stages = _stages(plan_id)
    stages[1]["cases"] = {"plan_id": plan_id, "case_keys": case_keys}
    if run_scope:
        stages[1]["scope"] = "run"
    _seed_run(
        conn,
        run_id=RUN,
        stages=stages,
        members=(MEMBER + 1,),
        existing_members=(MEMBER,),
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=None if run_scope else MEMBER,
    )


def _begin(conn, **kwargs):
    seed_registered_qa_launch(conn, SESSION)
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=kwargs.pop("deployment_member_item_id", MEMBER),
        actor_id="1",
        session_id=SESSION,
        **kwargs,
    )


def _case_begin(execution, ordinal=0):
    return handle_plan_case_begin(
        FunctionCallRequest(
            function="test_machine.plan_case.begin",
            actor=ActorContext(actor_id="1", session_id=SESSION),
            target=(TargetRef(kind="global", project_id="yoke")),
            payload={
                "execution_id": execution["id"],
                "ordinal": ordinal,
                "requirement_id": execution["roster"][ordinal]["requirement_id"],
            },
        )
    )
