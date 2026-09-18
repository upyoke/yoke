"""Seed an already-frozen deployment run for scoped (schema-2) QA stages.

The serving runtime's own creation-time gate (``require_supported_defini
tion_schema``) refuses to START a new run against a schema-2 (QA-stage)
flow through ``deployment_runs.create`` at all — a deliberate gate: "keep
the definition disabled until the matching runtime is deployed." Tests
that need to execute a real scoped-QA stage (via ``deploy_pipeline.run_
pipeline`` or the lower-level materialize/gate calls directly) seed an
already-admitted, already-frozen run instead, exactly as this module does
and as ``test_deployment_qa_stage_execution.py`` does inline.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_flow_requirements,
    snapshot_member_requirements,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


def create_smoke_plan(conn: Any, *, project: str, slug: str) -> int:
    """A one-case "command: true" QA plan, frozen onto a stage's ``cases``."""
    plan = create_plan(
        conn, project=project, slug=slug, name=slug, infer_target_environment=False
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


def seed_frozen_scoped_qa_run(
    conn: Any,
    *,
    run_id: str,
    project: str,
    flow: str,
    stages: list[dict],
    item_id: int,
    lineage: str,
) -> None:
    """Insert a run already admitted and frozen against ``stages``.

    Mirrors what ``freeze_run_composition`` would compute on a real
    "executing" transition, so the seeded row is indistinguishable from
    one that arrived here through the normal execution lifecycle.
    """
    project_id = resolve_project_id(conn, project)
    flow_snapshot = snapshot_flow_requirements(
        conn, flow_id=flow, project_id=project_id, stages=stages
    )
    now = iso8601_now()
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,current_stage,created_at,"
        "composition_frozen_at,requirement_snapshot"
        ") VALUES (%s,%s,%s,%s,'created',NULL,%s,%s,%s)",
        (run_id, project_id, flow, lineage, now, now, flow_snapshot),
    )
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        project=project,
        workflow_id="issue",
        # "done", not "implemented": the pipeline only stamps an
        # "implemented" member to release, which needs its own QA
        # requirement gate satisfied — an unrelated backlog-lifecycle
        # concern callers of this seed do not exercise.
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
        (run_id, item_id, now, member_snapshot),
    )
    conn.commit()


def seed_run_standing_on_qa_stage(
    conn: Any,
    *,
    run_id: str,
    project: str,
    stages: list[dict],
    members: tuple[int, ...],
    lineage: str,
    environment: str = "stage",
    environment_url: str = "https://preview.example.test",
) -> None:
    """Seed a frozen run parked on its item QA stage with deploy done.

    ``seed_frozen_scoped_qa_run`` stops at admission, which is enough for
    callers testing composition. Anything asking what the *gate* says needs
    the run to have actually reached the QA stage: an environment to point
    at, a ready deploy receipt naming the served lineage, and the run's
    cursor moved onto the QA stage. Seeding those three together keeps
    callers from each inventing a slightly different "deployed" state.
    """
    from yoke_core.domain.deployment_flow_versioning import cmd_create
    from yoke_core.domain.deployment_stage_receipts import (
        allocate_deployment_stage_receipt,
        complete_deployment_stage_receipt,
    )

    project_id = resolve_project_id(conn, project)
    now = iso8601_now()
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,%s,%s,%s,'{}',%s FROM sites "
        "WHERE project_id=%s ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        (project_id, environment, environment_url, now, project_id),
    )
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn, flow_id, project, flow_id, "", json.dumps(stages), status="disabled"
    )
    flow_snapshot = snapshot_flow_requirements(
        conn, flow_id=flow_id, project_id=project_id, stages=stages
    )
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,current_stage,created_at,"
        "composition_frozen_at,requirement_snapshot"
        ") VALUES (%s,%s,%s,%s,'executing',%s,%s,%s,%s)",
        (
            run_id,
            project_id,
            flow_id,
            lineage,
            str(stages[0]["name"]),
            now,
            now,
            flow_snapshot,
        ),
    )
    for item_id in members:
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            project=project,
            workflow_id="issue",
            status="done",
        )
        conn.execute(
            "INSERT INTO deployment_run_items("
            "run_id,item_id,added_at,requirement_snapshot"
            ") VALUES (%s,%s,%s,%s)",
            (
                run_id,
                item_id,
                now,
                snapshot_member_requirements(
                    conn,
                    run_id=run_id,
                    item_id=item_id,
                    selection_json=requirement_selection(),
                ),
            ),
        )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=run_id,
        stage_name=str(stages[0]["name"]),
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
        observed_url=environment_url,
        observed_release_lineage=lineage,
        executor_receipt="test://deploy-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
        (str(stages[1]["name"]), run_id),
    )
    conn.commit()



#: The one item-scoped QA stage these helpers seed, named once so a test and
#: the fixture cannot drift apart on the string.
ITEM_QA_STAGE = "item-qa"


def item_qa_stage_definitions(plan_id: int, *, environment: str = "stage") -> list[dict]:
    """A deploy stage followed by the item-scoped QA stage it feeds."""
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": ITEM_QA_STAGE,
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": environment,
                "source_stage": "deploy",
            },
            "cases": {"plan_id": plan_id, "case_keys": ["command-smoke"]},
            "verdict": {"mode": "agent_only"},
        },
    ]


def seed_member_qa_case(
    conn: Any,
    *,
    run_id: str,
    member_item_id: int,
    project: str = "yoke",
    lineage: str = "b" * 40,
) -> int:
    """Seed a member parked on the QA stage; return its materialized case id."""
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )

    plan_id = create_smoke_plan(conn, project=project, slug=f"smoke-{run_id}")
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project=project,
        stages=item_qa_stage_definitions(plan_id),
        members=(member_item_id,),
        lineage=lineage,
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=member_item_id,
    )
    row = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND deployment_member_item_id=%s "
        "AND method_id IS NOT NULL ORDER BY id",
        (run_id, ITEM_QA_STAGE, member_item_id),
    ).fetchone()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def record_case_verdict(
    conn: Any, requirement_id: int, verdict: str, *, evidence: bool
) -> int:
    """Record one verdict, with or without the evidence the gate looks for."""
    now = "2026-09-18T00:02:00Z"
    qa_run_id = int(
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
            "started_at,completed_at,created_at) "
            "VALUES (%s,'worktree_run','plan_case',%s,%s,%s,%s) RETURNING id",
            (int(requirement_id), verdict, now, now, now),
        ).fetchone()[0]
    )
    if evidence:
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
            (qa_run_id, f"evidence://requirement-{requirement_id}", now),
        )
    conn.commit()
    return qa_run_id


__all__ = [
    "ITEM_QA_STAGE",
    "create_smoke_plan",
    "item_qa_stage_definitions",
    "record_case_verdict",
    "seed_frozen_scoped_qa_run",
    "seed_member_qa_case",
    "seed_run_standing_on_qa_stage",
]
