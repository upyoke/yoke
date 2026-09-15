"""Frozen member obligations and executor-selected deployment QA cases."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _environment,
    _plan,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_flow_versioning import cmd_create
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
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import QaPlanError


def _stage(environment: str = "stage") -> dict[str, Any]:
    return {
        "name": "member-qa",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
        "target": {
            "kind": "persistent_environment",
            "environment": environment,
            "source_stage": "deploy",
        },
        "verdict": {"mode": "agent_only"},
    }


def _seed_selected_requirement_run(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    requirement_id: int,
    environment: str = "stage",
) -> None:
    _environment(conn)
    if environment != "stage":
        conn.execute(
            "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
            "SELECT id,1,%s,%s,'{}',%s FROM sites WHERE project_id=1 "
            "ORDER BY id LIMIT 1 ON CONFLICT(project_id,name) DO NOTHING",
            (
                environment,
                f"https://{environment}.example.test",
                "2026-09-14T00:00:00Z",
            ),
        )
    stages = [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        _stage(environment),
    ]
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
            "c" * 40,
            "2026-09-14T00:00:00Z",
            "2026-09-14T00:01:00Z",
            flow_snapshot,
        ),
    )
    member_snapshot = snapshot_member_requirements(
        conn,
        run_id=run_id,
        item_id=item_id,
        selection_json=requirement_selection(requirement_ids=(requirement_id,)),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES (%s,%s,%s,%s)",
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
        target_name=environment,
        observed_url=f"https://{environment}.example.test"
        if environment != "stage"
        else "https://preview.example.test",
        observed_release_lineage="c" * 40,
        executor_receipt="test://deploy-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage='member-qa' WHERE id=%s",
        (run_id,),
    )
    conn.commit()


def _original_requirement(
    conn: Any, *, item_id: int, method_id: str | None
) -> int:
    columns = [
        "item_id", "qa_kind", "qa_phase", "target_env", "blocking_mode",
        "requirement_source", "instructions", "expected_outcome", "created_at",
    ]
    values: list[Any] = [
        item_id, "visual_acceptance", "post_deploy", "stage", "blocking", "explicit",
        "Capture the deployed release summary before accepting it.",
        "The release summary shows the admitted item and running revision.",
        "2026-09-14T00:00:00Z",
    ]
    if method_id is not None:
        method = conn.execute(
            "SELECT name,runner_id,required_capability_kinds,verdict_path "
            "FROM qa_methods WHERE id=%s",
            (method_id,),
        ).fetchone()
        columns.extend(
            [
                "method_id", "method_name", "runner_id", "capability_requirements",
                "verdict_path", "method_config",
            ]
        )
        values.extend(
            [
                method_id, method["name"], method["runner_id"],
                method["required_capability_kinds"], method["verdict_path"],
                json.dumps(
                    {
                        "steps": [
                            {"action": "navigate", "route": "/releases/current"},
                            {"action": "screenshot", "capture": True},
                        ]
                    }
                ),
            ]
        )
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) VALUES "
        f"({','.join('%s' for _ in columns)}) RETURNING id",
        tuple(values),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def test_explicit_screenshot_obligation_materializes_before_execution(test_db) -> None:
    item_id = 9710
    insert_item(test_db, id=item_id, project_sequence=710, workflow_id="issue", status="done")
    original_id = _original_requirement(
        test_db, item_id=item_id, method_id="browser-inspection"
    )
    _seed_selected_requirement_run(
        test_db, run_id="run-admitted-screenshot", item_id=item_id,
        requirement_id=original_id,
    )

    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-admitted-screenshot",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    assert len(result["created_requirement_ids"]) == 1
    roster = ordered_plan_requirements(
        test_db,
        deployment_run_id="run-admitted-screenshot",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    assert roster[0]["plan_id"] is None
    assert roster[0]["case_key"] == f"admitted-requirement-{original_id}"
    scoped = test_db.execute(
        "SELECT item_id,deployment_member_item_id,method_id,execution_target_json "
        "FROM qa_requirements WHERE id=%s", (roster[0]["requirement_id"],)
    ).fetchone()
    assert scoped["item_id"] is None and scoped["deployment_member_item_id"] == item_id
    target = json.loads(scoped["execution_target_json"])
    assert target["environment"]["name"] == "stage"
    assert target["deployment"]["release_lineage"] == "c" * 40
    assert test_db.execute(
        "SELECT item_id FROM qa_requirements WHERE id=%s", (original_id,)
    ).fetchone()["item_id"] == item_id


def test_agent_selected_plan_stays_distinct_from_admitted_obligation(test_db) -> None:
    item_id = 9711
    insert_item(test_db, id=item_id, project_sequence=711, workflow_id="issue", status="done")
    original_id = _original_requirement(test_db, item_id=item_id, method_id=None)
    plan_id = _plan(test_db, "agent-selected-release")
    _seed_selected_requirement_run(
        test_db, run_id="run-agent-selection", item_id=item_id,
        requirement_id=original_id,
    )
    with pytest.raises(QaPlanError, match="select a project QA plan"):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-agent-selection",
            deployment_stage="member-qa",
            deployment_member_item_id=item_id,
        )
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-agent-selection",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
    )
    assert len(result["created_requirement_ids"]) == 2
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-agent-selection",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="agent-selection",
    )
    assert [case["plan_id"] for case in execution["roster"]] == [plan_id]
    _complete_case(test_db, execution)
    blocked = deployment_qa_stage_status(
        test_db, run_id="run-agent-selection", stage_name="member-qa",
        member_item_id=item_id,
    )
    assert not blocked["accepted"]
    assert any("no explicit verdict" in reason for reason in blocked["reasons"])
    case_run_id = int(
        test_db.execute(
            "SELECT r.id FROM qa_runs r JOIN qa_requirements q "
            "ON q.id=r.qa_requirement_id WHERE q.deployment_run_id=%s "
            "AND q.method_id IS NOT NULL ORDER BY r.id DESC LIMIT 1",
            ("run-agent-selection",),
        ).fetchone()["id"]
    )
    artifact_id = int(
        test_db.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES (%s,'log','text/plain',%s,%s) "
            "RETURNING id",
            (case_run_id, "evidence://release-summary", "2026-09-14T00:03:00Z"),
        ).fetchone()["id"]
    )
    scoped_obligation_id = int(
        test_db.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND plan_id IS NULL AND method_id IS NULL",
            ("run-agent-selection",),
        ).fetchone()["id"]
    )
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) "
        "VALUES (%s,'agent','visual_acceptance','pass',%s,%s,%s,%s)",
        (
            scoped_obligation_id,
            json.dumps(
                {
                    "execution_id": execution["id"],
                    "evidence_artifact_ids": [artifact_id],
                }
            ),
            "2026-09-14T00:04:00Z",
            "2026-09-14T00:04:00Z",
            "2026-09-14T00:04:00Z",
        ),
    )
    test_db.commit()
    assert deployment_qa_stage_status(
        test_db,
        run_id="run-agent-selection",
        stage_name="member-qa",
        member_item_id=item_id,
    )["accepted"]
    admitted = test_db.execute(
        "SELECT qrun.verdict,qrun.raw_result FROM qa_requirements q "
        "JOIN qa_runs qrun ON qrun.qa_requirement_id=q.id "
        "WHERE q.deployment_run_id='run-agent-selection' AND q.plan_id IS NULL "
        "AND q.qa_kind<>'deployment_stage_acceptance'"
    ).fetchone()
    assert admitted["verdict"] == "pass"
    assert json.loads(admitted["raw_result"])["execution_id"] == execution["id"]
