"""Scoped deployment QA execution, target, and verdict coverage."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_flow_versioning import cmd_create
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
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_flow_requirements,
    snapshot_member_requirements,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


def _environment(conn: Any) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'stage','https://preview.example.test','{}',%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        ("2026-09-14T00:00:00Z",),
    )


def _plan(conn: Any, slug: str = "release-smoke") -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug=slug,
        name="Release smoke",
        infer_target_environment=False,
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "run the frozen smoke command",
                "expected_outcome": "the command passes",
                "method_config": {"command": "true"},
            }
        ],
    )
    return int(plan["id"])


def _stages(plan_id: int, *, verdict: dict | None = None) -> list[dict[str, Any]]:
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy",
            },
            "cases": {"plan_id": plan_id, "case_keys": ["command-smoke"]},
            "verdict": verdict or {"mode": "agent_only"},
        },
    ]


def _seed_run(
    conn: Any,
    *,
    run_id: str,
    stages: list[dict[str, Any]],
    members: tuple[int, ...],
    existing_members: tuple[int, ...] = (),
    release_lineage: str = "a" * 40,
) -> None:
    """Seed a frozen schema-2 run, its members, and a ready stage receipt.

    ``members`` are created here; ``existing_members`` are items the
    caller already inserted with the status and pin its own test needs,
    and are attached without being created again.
    """
    _environment(conn)
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps(stages),
        status="disabled",
    )
    flow_snapshot = snapshot_flow_requirements(
        conn, flow_id=flow_id, project_id=1, stages=stages
    )
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,current_stage,created_at,"
        "composition_frozen_at,requirement_snapshot"
        ") VALUES (%s,1,%s,%s,'executing','deploy',%s,%s,%s)",
        (
            run_id,
            flow_id,
            release_lineage,
            "2026-09-14T00:00:00Z",
            "2026-09-14T00:01:00Z",
            flow_snapshot,
        ),
    )
    for item_id in (*members, *existing_members):
        if item_id in members:
            insert_item(
                conn,
                id=item_id,
                project_sequence=item_id,
                workflow_id="issue",
                status="done",
            )
        member_snapshot = snapshot_member_requirements(
            conn,
            run_id=run_id,
            item_id=item_id,
            selection_json=requirement_selection(),
        )
        conn.execute(
            "INSERT INTO deployment_run_items("
            "run_id,item_id,added_at,requirement_snapshot"
            ") VALUES (%s,%s,%s,%s)",
            (run_id, item_id, "2026-09-14T00:00:00Z", member_snapshot),
        )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=run_id,
        stage_name="deploy",
        correlation_id=f"{run_id}-deploy-1",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=run_id,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage=release_lineage,
        executor_receipt="test://deploy-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
        (str(stages[1]["name"]), run_id),
    )
    conn.commit()


def _complete_case(conn: Any, execution: dict[str, Any]) -> int:
    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-09-14T00:02:00Z"
    run_id = int(
        conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,started_at,completed_at,created_at"
        ") VALUES (%s,'worktree_run','plan_case','pass',%s,%s,%s) RETURNING id",
        (requirement_id, now, now, now),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
        (run_id, "evidence://scoped-case", now),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": run_id,
        },
    )
    finish_plan_execution(
        conn,
        execution,
        state="completed",
        reason="test-complete",
    )
    return requirement_id


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
    assert any("no completed" in reason for reason in blocked["reasons"])


def test_frozen_plan_survives_edit_and_replaced_candidate_refuses_results(
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
    test_db.execute(
        "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s",
        ("b" * 40, "run-frozen-stage"),
    )
    test_db.commit()
    with pytest.raises(ValueError, match="replaced"):
        validate_deployment_execution_target(test_db, execution)
