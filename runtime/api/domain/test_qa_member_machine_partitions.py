"""Multi-host member QA preserves leases, evidence scope and every obligation."""

from __future__ import annotations


import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
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
    conn, tmp_path, monkeypatch, *, split_plans=False, simultaneous=False, driver=None
):
    configure_test_machine(conn, tmp_path, monkeypatch)
    replace_test_machine_settings(
        conn,
        project="yoke",
        machine=MACHINES[1],
        settings={**TEST_MACHINE_SETTINGS, "resource_name": MACHINES[1]},
        base_settings=None,
    )
    plans = []
    for index in range(2 if split_plans else 1):
        plan = create_plan(
            conn,
            project="yoke",
            slug=f"host-check-{index}",
            infer_target_environment=False,
        )
        machines = (
            [driver or MACHINES[0]]
            if simultaneous
            else [MACHINES[index]]
            if split_plans
            else MACHINES
        )
        replace_plan_cases(
            conn,
            plan_id=int(plan["id"]),
            cases=[
                {
                    "case_key": machine,
                    "position": position,
                    "method_id": "terminal-check",
                    "instructions": "Run a host-specific check.",
                    "expected_outcome": "The check passes.",
                    "method_config": {
                        **_terminal_recipe(),
                        "machine": machine,
                        **({"machines": list(MACHINES)} if simultaneous else {}),
                    },
                    "entry_surface": "printf done",
                    "required_completion": "complete",
                }
                for position, machine in enumerate(machines, 1)
            ],
        )
        plans.append(int(plan["id"]))
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

    insert_item(
        conn, id=MEMBER, project_sequence=MEMBER, workflow_id="issue", status="done"
    )
    for plan_id in plans:
        attach_plan_to_item(
            conn,
            plan_id=plan_id,
            item_id=MEMBER,
            transition_id="release",
            qa_phase="post_deploy",
        )
    stages = _stages(plans[0])
    stages[1].pop("cases")
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
        deployment_member_item_id=MEMBER,
    )


def _begin(conn, **kwargs):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id=SESSION,
        **kwargs,
    )


def _case_begin(execution):
    return handle_plan_case_begin(
        FunctionCallRequest(
            function="test_machine.plan_case.begin",
            actor=ActorContext(actor_id="2", session_id=SESSION),
            target=TargetRef(kind="deployment_run", deployment_run_id=RUN),
            payload={
                "execution_id": execution["id"],
                "ordinal": 0,
                "requirement_id": execution["roster"][0]["requirement_id"],
            },
        )
    )


@pytest.mark.parametrize("split_plans", [False, True])
def test_each_host_has_its_own_execution_and_member_waits_for_both(
    test_db, tmp_path, monkeypatch, split_plans
):
    _seed(test_db, tmp_path, monkeypatch, split_plans=split_plans)
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
        _begin(test_db, machine=MACHINES[0])
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
    test_db.execute(
        "UPDATE qa_runs SET verdict='fail' WHERE qa_requirement_id=%s",
        (requirement_id,),
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
