"""Multi-host member QA preserves leases, evidence scope and every obligation."""

from __future__ import annotations


import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    _terminal_recipe,
    configure_test_machine,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
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
                "starting_state": "inherit"
                if inherit and position == 2
                else "as_is",
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


def test_each_host_has_its_own_execution_and_member_waits_for_both(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    first = _begin(test_db)
    assert first["remaining_requirement_count"] == 1
    assert [case["case_key"] for case in first["roster"]] == [MACHINES[0]]
    contract = _case_begin(first)
    assert contract.primary_success, contract.error
    lease_id = contract.result_payload["execution"]["lease_id"]
    assert _begin(test_db)["id"] == first["id"]
    _complete_case(test_db, lock_plan_execution(test_db, first["id"]))
    assert test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (lease_id,)
    ).fetchone()[0]
    status = deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBER
    )
    assert not status["accepted"]
    second = _begin(test_db)
    assert second["id"] != first["id"]
    assert second["remaining_requirement_count"] == 0
    assert [case["case_key"] for case in second["roster"]] == [MACHINES[1]]
    assert _begin(test_db)["id"] == second["id"]
    contract = _case_begin(second)
    assert contract.primary_success, contract.error
    assert contract.result_payload["execution"]["lease_id"] != lease_id
    _complete_case(test_db, lock_plan_execution(test_db, second["id"]))
    assert deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBER
    )["accepted"]
    assert _begin(test_db)["state"] == "completed"
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage='item-qa' AND deployment_member_item_id=%s AND method_id IS NOT NULL",
            (RUN, MEMBER),
        ).fetchone()[0]
        == 2
    )


def test_a_host_pin_cannot_drop_another_required_host(test_db, tmp_path, monkeypatch):
    _seed(test_db, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="test_machine_constraint_mismatch"):
        _begin(test_db, test_machine=MACHINES[0])
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


def test_waiting_second_host_keeps_its_partition_and_fifo(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    _complete_case(test_db, _begin(test_db))
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session

    seed_qa_session(test_db, SESSION, "occupied-host", messageable=True)
    held = acquire(test_db, make_qa_admission_target(MACHINES[1]), "occupied-host")
    second = _begin(test_db)
    response = _case_begin(second)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "waiting"
    release(test_db, held.id, "host-free")
    resumed = _begin(test_db)
    assert resumed["id"] == second["id"] and resumed["remaining_requirement_count"] == 0
    assert _case_begin(resumed).result_payload["state"] == "ready"


def test_completed_capture_without_current_passing_evidence_is_retried(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    first = _begin(test_db)
    requirement_id = _complete_case(test_db, first)
    from runtime.api.fixtures.backlog_inserts import insert_qa_run

    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="fail",
        qa_kind="plan_case",
        performed_by="worktree_run",
    )
    test_db.commit()
    retry = _begin(test_db)
    assert retry["id"] != first["id"]
    assert retry["roster"][0]["requirement_id"] == requirement_id
    assert retry["remaining_requirement_count"] == 1


def test_an_unscoped_pass_does_not_cover_a_required_host(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    requirements = test_db.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s AND method_id IS NOT NULL ORDER BY id",
        (RUN,),
    ).fetchall()
    for row in requirements:
        test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,started_at,completed_at,created_at) VALUES (%s,'agent','plan_case','pass',%s,%s,%s)",
            (row[0], *(["2026-09-14T00:02:00Z"] * 3)),
        )
    test_db.commit()
    first = _begin(test_db)
    assert first["remaining_requirement_count"] == 1
    assert first["roster"][0]["case_key"] == MACHINES[0]


@pytest.mark.parametrize(
    "mission,trailing", [(False, False), (True, False), (True, True)]
)
def test_inherit_chain_holds_its_host_union_before_the_opener(
    test_db, tmp_path, monkeypatch, mission, trailing
):
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases
    from yoke_core.domain.qa_plan_execution_state import advance_plan_execution

    _seed(
        test_db, tmp_path, monkeypatch, inherit=True, mission=mission, trailing=trailing
    )
    first = _begin(test_db)
    assert first["remaining_requirement_count"] == int(trailing)
    assert len(first["roster"]) == 2
    response = _case_begin(first)
    assert response.primary_success, response.error
    current = lock_plan_execution(test_db, first["id"])
    leases = execution_host_leases(test_db, current)
    assert [claim.target.test_machine for claim in leases] == list(MACHINES)
    opener = current["roster"][0]
    advance_plan_execution(
        test_db,
        current,
        ordinal=0,
        requirement_id=opener["requirement_id"],
        result={"requirement_id": opener["requirement_id"], "case_outcome": "passed"},
    )
    assert _begin(test_db)["id"] == first["id"]
    response = _case_begin(current, 1)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "ready"
    assert [claim.id for claim in execution_host_leases(test_db, current)] == [
        claim.id for claim in leases
    ]
