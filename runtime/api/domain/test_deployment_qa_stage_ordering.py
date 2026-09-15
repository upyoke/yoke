"""Ordered deployment QA stages cannot collide or bypass earlier members."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_resume import (
    prior_deployment_qa_refusals,
)
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)


def _qa_stage(name: str, plan_id: int, scope: str = "item") -> dict[str, Any]:
    return {
        "name": name,
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": scope,
        "target": {
            "kind": "persistent_environment",
            "environment": "stage",
            "source_stage": "deploy",
        },
        "cases": {"plan_id": plan_id, "case_keys": ["command-smoke"]},
        "verdict": {"mode": "agent_only"},
    }


def _stages(plan_id: int) -> list[dict[str, Any]]:
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        _qa_stage("member-qa-one", plan_id),
        _qa_stage("member-qa-two", plan_id),
        _qa_stage("release-qa", plan_id, "run"),
    ]


def _begin(conn: Any, run_id: str, stage: str, member: int | None) -> dict[str, Any]:
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=stage,
        deployment_member_item_id=member,
    )
    return begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=stage,
        deployment_member_item_id=member,
        actor_id="2",
        session_id=f"{stage}-{member}",
    )


def _complete_failed(conn: Any, execution: dict[str, Any]) -> None:
    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-09-14T00:02:00Z"
    conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,started_at,completed_at,created_at"
        ") VALUES (%s,'worktree_run','plan_case','fail',%s,%s,%s)",
        (requirement_id, now, now, now),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "fail",
            "case_outcome": "failed",
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-failed")


def test_same_method_member_stages_keep_distinct_requirements_and_executions(
    test_db,
) -> None:
    plan_id = _plan(test_db, "repeated-stage-method")
    stages = _stages(plan_id)
    member = 9720
    _seed_run(test_db, run_id="run-repeated-stages", stages=stages, members=(member,))

    first = _begin(test_db, "run-repeated-stages", "member-qa-one", member)
    _complete_case(test_db, first)
    assert deployment_qa_stage_status(
        test_db, run_id="run-repeated-stages", stage_name="member-qa-one",
        member_item_id=member,
    )["accepted"]
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='member-qa-two' "
        "WHERE id='run-repeated-stages'"
    )
    test_db.commit()
    second = _begin(test_db, "run-repeated-stages", "member-qa-two", member)
    assert first["id"] != second["id"]
    assert first["roster"][0]["requirement_id"] != second["roster"][0]["requirement_id"]
    _complete_case(test_db, second)
    assert deployment_qa_stage_status(
        test_db, run_id="run-repeated-stages", stage_name="member-qa-two",
        member_item_id=member,
    )["accepted"]


def test_failed_done_member_blocks_run_qa_and_resume_even_with_continue(test_db) -> None:
    plan_id = _plan(test_db, "member-failure-gate")
    stages = _stages(plan_id)
    members = (9721, 9722)
    _seed_run(test_db, run_id="run-member-failure", stages=stages, members=members)
    test_db.execute(
        "UPDATE deployment_flows SET on_failure='continue' WHERE id='flow-run-member-failure'"
    )
    test_db.commit()

    failed = _begin(test_db, "run-member-failure", "member-qa-one", members[0])
    passed = _begin(test_db, "run-member-failure", "member-qa-one", members[1])
    _complete_failed(test_db, failed)
    _complete_case(test_db, passed)
    assert not deployment_qa_stage_status(
        test_db, run_id="run-member-failure", stage_name="member-qa-one",
        member_item_id=members[0],
    )["accepted"]
    assert deployment_qa_stage_status(
        test_db, run_id="run-member-failure", stage_name="member-qa-one",
        member_item_id=members[1],
    )["accepted"]
    refusals = prior_deployment_qa_refusals(
        test_db,
        run_id="run-member-failure",
        stages=stages,
        start_stage="release-qa",
    )
    assert any("member 9721" in refusal for refusal in refusals)

    test_db.execute(
        "UPDATE deployment_runs SET current_stage='release-qa' "
        "WHERE id='run-member-failure'"
    )
    test_db.commit()
    with pytest.raises(ValueError, match="prior scoped QA acceptance"):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-member-failure",
            deployment_stage="release-qa",
        )
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage='release-qa'",
        ("run-member-failure",),
    ).fetchone()[0] == 0


def test_new_producer_attempt_invalidates_and_can_replace_prior_acceptance(
    test_db,
) -> None:
    plan_id = _plan(test_db, "receipt-replay-gate")
    stages = _stages(plan_id)
    member = 9723
    run_id = "run-receipt-replay"
    _seed_run(test_db, run_id=run_id, stages=stages, members=(member,))
    first = _begin(test_db, run_id, "member-qa-one", member)
    _complete_case(test_db, first)
    assert deployment_qa_stage_status(
        test_db,
        run_id=run_id,
        stage_name="member-qa-one",
        member_item_id=member,
    )["accepted"]

    test_db.execute(
        "UPDATE deployment_runs SET current_stage='deploy' WHERE id=%s", (run_id,)
    )
    replacement = allocate_deployment_stage_receipt(
        test_db,
        run_id=run_id,
        stage_name="deploy",
        correlation_id="replacement-deploy",
        target_kind="persistent_environment",
        executor="test",
    )
    complete_deployment_stage_receipt(
        test_db,
        run_id=run_id,
        receipt_id=int(replacement["id"]),
        correlation_id="replacement-deploy",
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage="a" * 40,
        executor_receipt="test://replacement-ready",
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='member-qa-two' WHERE id=%s",
        (run_id,),
    )
    test_db.commit()
    refusals = prior_deployment_qa_refusals(
        test_db,
        run_id=run_id,
        stages=stages,
        start_stage="member-qa-two",
    )
    assert any("receipt was superseded" in refusal for refusal in refusals)

    test_db.execute(
        "UPDATE deployment_runs SET current_stage='member-qa-one' WHERE id=%s",
        (run_id,),
    )
    test_db.commit()
    second = _begin(test_db, run_id, "member-qa-one", member)
    _complete_case(test_db, second)
    assert deployment_qa_stage_status(
        test_db,
        run_id=run_id,
        stage_name="member-qa-one",
        member_item_id=member,
    )["accepted"]
    assert first["id"] != second["id"]
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage='member-qa-one' "
        "AND qa_kind='deployment_stage_acceptance'",
        (run_id,),
    ).fetchone()[0] == 2

    test_db.execute(
        "UPDATE deployment_runs SET current_stage='member-qa-two' WHERE id=%s",
        (run_id,),
    )
    test_db.commit()
    assert prior_deployment_qa_refusals(
        test_db,
        run_id=run_id,
        stages=stages,
        start_stage="member-qa-two",
    ) == []
