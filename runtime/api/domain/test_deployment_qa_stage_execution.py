"""Scoped deployment QA execution, target, and verdict coverage."""

from __future__ import annotations

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case as _complete_case,
    _environment as _environment,
    _plan as _plan,
    _seed_run as _seed_run,
    _stages as _stages,
)


from yoke_core.domain.deployment_qa_execution_target import (
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
)


def test_done_members_keep_independent_stage_executions_and_gates(test_db) -> None:
    plan_id = _plan(test_db)
    _seed_run(
        test_db,
        run_id="run-scoped-members",
        stages=_stages(plan_id),
        members=(9701, 9702),
    )
    executions = []
    for member in (9701, 9702):
        materialized = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-scoped-members",
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
        assert materialized["candidate_revision"] == "a" * 40
        executions.append(
            begin_plan_execution(
                test_db,
                deployment_run_id="run-scoped-members",
                deployment_stage="item-qa",
                deployment_member_item_id=member,
                actor_id="2",
                session_id="member-qa",
            )
        )
    assert executions[0]["id"] != executions[1]["id"]
    _complete_case(test_db, executions[0])
    assert deployment_qa_stage_status(
        test_db,
        run_id="run-scoped-members",
        stage_name="item-qa",
        member_item_id=9701,
    )["accepted"]
    blocked = deployment_qa_stage_status(
        test_db,
        run_id="run-scoped-members",
        stage_name="item-qa",
        member_item_id=9702,
    )
    assert not blocked["accepted"]
    assert any("yoke qa case run --requirement-id" in reason for reason in blocked["reasons"])


def test_frozen_plan_survives_edit_and_a_newer_receipt_keeps_writing(
    test_db,
) -> None:
    plan_id = _plan(test_db, "frozen-release-smoke")
    _seed_run(
        test_db,
        run_id="run-frozen-stage",
        stages=_stages(plan_id),
        members=(9703,),
    )
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='edited after admission' "
        "WHERE plan_id=%s",
        (plan_id,),
    )
    test_db.commit()
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-frozen-stage",
        deployment_stage="item-qa",
        deployment_member_item_id=9703,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-frozen-stage",
        deployment_stage="item-qa",
        deployment_member_item_id=9703,
        actor_id="2",
        session_id="frozen-qa",
    )
    assert execution["roster"][0]["instructions"] == "run the frozen smoke command"
    # A redeploy mid-stage records a newer ready receipt. QA tests whatever is
    # deployed, so the frozen receipt is provenance and the walk keeps writing.
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='deploy' WHERE id=%s",
        ("run-frozen-stage",),
    )
    receipt = allocate_deployment_stage_receipt(
        test_db,
        run_id="run-frozen-stage",
        stage_name="deploy",
        correlation_id="run-frozen-stage-deploy-2",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        test_db,
        run_id="run-frozen-stage",
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage="a" * 40,
        executor_receipt="test://deploy-ready-again",
        commit=False,
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s",
        ("run-frozen-stage",),
    )
    test_db.commit()
    validate_deployment_execution_target(test_db, execution)
