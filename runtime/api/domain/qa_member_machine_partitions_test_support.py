# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

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

RUN = "run-member-hosts"

MEMBER = 9820

SESSION = "session-machine-plan"


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
    replace_test_machine_settings(
        conn,
        project="yoke",
        test_machine=MACHINES[1],
        settings={**TEST_MACHINE_SETTINGS, "resource_name": MACHINES[1]},
        base_settings=None,
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug="host-check-0",
        infer_target_environment=False,
    )
    machines = [driver or MACHINES[0]] if simultaneous else list(MACHINES)
    if trailing:
        machines = [*machines, "independent"]
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": test_machine,
                "position": position,
                "method_id": "exploratory-mission"
                if mission and position == 2
                else "terminal-check",
                "instructions": "Run a host-specific check.",
                "expected_outcome": "The check passes.",
                "method_config": {
                    **({} if mission and position == 2 else _terminal_recipe()),
                    "test_machine": MACHINES[0] if inherit else test_machine,
                    **(
                        {"executor": "informed_subagent"}
                        if mission and position == 2
                        else {}
                    ),
                    **(
                        {"test_machines": list(MACHINES)}
                        if simultaneous or (inherit and position == 2)
                        else {}
                    ),
                },
                "entry_surface": "printf done",
                "required_completion": "complete",
                "starting_state": "inherit" if inherit and position == 2 else "as_is",
                "starting_state_reason": (
                    None
                    if inherit and position == 2
                    else "The check reads host identity only and needs no reset."
                ),
            }
            for position, test_machine in enumerate(machines, 1)
        ],
    )
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        conn, id=MEMBER, project_sequence=MEMBER, workflow_id="issue", status="done"
    )
    # The flow pins the plan's cases to the stage, so each member walks its own
    # copy; an attached post-deploy plan would run as a memberless plan group.
    stages = _stages(int(plan["id"]))
    stages[1]["cases"] = {"plan_id": int(plan["id"]), "case_keys": machines}
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
