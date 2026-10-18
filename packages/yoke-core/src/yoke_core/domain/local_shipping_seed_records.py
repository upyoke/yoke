"""Shipping review records composed through their existing registered writers."""

import json

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import connect

PROJECTS = ("shipping-review-visible", "shipping-review-hidden")
RUN_PREFIX = "shipping-review-"
LINEAGE = "f" * 40
FLOW = "shipping-review-flow"


def write(handler, function, payload, actor):
    outcome = handler(
        FunctionCallRequest(
            function=function,
            actor={"actor_id": str(actor), "session_id": ""},
            target={"kind": "global"},
            payload=payload,
        )
    )
    if not outcome.primary_success:
        raise RuntimeError(f"shipping_seed_write_refused: {function}: {outcome.error}")
    return outcome.result_payload


def projects(actor):
    from yoke_core.domain.projects_upsert import cmd_upsert
    from yoke_core.domain.handlers.projects_infrastructure_create import (
        handle_projects_site_create,
        handle_projects_environment_create,
    )

    result = []
    for position, slug in enumerate(PROJECTS):
        row = cmd_upsert(
            slug=slug,
            name=slug.replace("-", " ").title(),
            public_item_prefix=("SRV", "SRH")[position],
        )["project"]
        write(
            handle_projects_site_create,
            "projects.site.create",
            {"project": slug, "site": "review"},
            actor,
        )
        write(
            handle_projects_environment_create,
            "projects.environment.create",
            {
                "project": slug,
                "site": "review",
                "environment": "local",
                "settings": {"role": {"production": False}},
            },
            actor,
        )
        result.append(row)
    return result


def items(project_rows, actor):
    from yoke_core.domain.backlog_create_op import execute_create

    result = []
    for position in range(17):
        project = project_rows[position % 2]
        title = f"Shipping review member {position + 1:02d}"
        with connect() as conn:
            existing = conn.execute(
                "SELECT id,status FROM items WHERE project_id=%s AND title=%s",
                (project["id"], title),
            ).fetchall()
        if len(existing) > 1 or (existing and existing[0]["status"] != "release"):
            raise RuntimeError(
                f"shipping_seed_item_collision: {title}; retain and inspect existing fixture"
            )
        if existing:
            item_id = int(existing[0]["id"])
        else:
            created = execute_create(
                title=title,
                workflow="dash",
                priority="medium",
                project=project["slug"],
                status="release",
                source=str(actor),
                owner=str(actor),
                deployment_flow=f"{FLOW}-{position % 2}",
                entry_surface="harness_skill",
                spec="Disposable Shipping review member; not real delivery work.",
            )
            if not created.get("success"):
                raise RuntimeError(
                    f"shipping_seed_item_refused: {created.get('error')}"
                )
            item_id = int(created["item_id"])
        result.append(
            {"item_id": item_id, "project_id": int(project["id"]), "title": title}
        )
    return result


def plans(project_rows, members, actor):
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

    ids = []
    for project in project_rows:
        with connect() as conn:
            found = conn.execute(
                "SELECT id FROM qa_plans WHERE project_id=%s AND slug='shipping-review-check'",
                (project["id"],),
            ).fetchone()
            plan_id = (
                int(found[0])
                if found
                else int(
                    create_plan(
                        conn,
                        project=project["slug"],
                        slug="shipping-review-check",
                        name="Shared review check",
                        target_environment="review/local",
                    )["id"]
                )
            )
            replace_plan_cases(
                conn,
                plan_id=plan_id,
                cases=[
                    {
                        "case_key": "review-check",
                        "method_id": "command",
                        "instructions": "Synthetic review obligation; not executed by the seed.",
                        "expected_outcome": "Queued until explicitly exercised in this review universe.",
                        "method_config": {"command": "true"},
                    }
                ],
            )
            for member in members:
                if member["project_id"] == int(project["id"]):
                    attach_plan_to_item(
                        conn,
                        plan_id=plan_id,
                        item_id=member["item_id"],
                        transition_id="release",
                        qa_phase="post_deploy",
                        actor_id=actor,
                    )
        ids.append(plan_id)
    return ids


def flow(project_rows):
    from yoke_core.domain.flow_create import cmd_create

    own, other = project_rows
    for position, project in enumerate(project_rows):
        completion_flow = f"{FLOW}-{position}"
        with connect() as conn:
            if not conn.execute(
                "SELECT id FROM deployment_flows WHERE id=%s", (completion_flow,)
            ).fetchone():
                cmd_create(
                    conn,
                    completion_flow,
                    project["slug"],
                    "Shipping review completion",
                    "Disposable completion identity; the seed never starts execution.",
                    json.dumps(
                        [
                            {
                                "name": "deploy",
                                "step_runner": "auto",
                                "stage_kind": "execution",
                                "scope": "run",
                            }
                        ]
                    ),
                    status="active",
                    takes_delivery_custody=True,
                )
    with connect() as conn:
        if not conn.execute(
            "SELECT id FROM deployment_flows WHERE id=%s", (FLOW,)
        ).fetchone():
            cmd_create(
                conn,
                FLOW,
                own["slug"],
                "Shipping review flow",
                "Disposable presentation fixtures; never drive this flow.",
                json.dumps(
                    [
                        {
                            "name": "deploy",
                            "step_runner": "auto",
                            "stage_kind": "execution",
                            "scope": "run",
                            "input_bindings": {
                                "hidden": {"project": other["slug"], "branch": "main"}
                            },
                        },
                        {
                            "name": "item-qa",
                            "step_runner": "qa",
                            "stage_kind": "qa",
                            "scope": "item",
                            "target": {
                                "kind": "persistent_environment",
                                "environment": "local",
                                "source_stage": "deploy",
                            },
                            "verdict": {"mode": "agent_only"},
                        },
                    ]
                ),
                status="disabled",
                takes_delivery_custody=True,
            )


def runs(project_rows, members):
    from yoke_core.domain.deployment_run_projection import project_snapshot
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item

    own, other = project_rows
    ids = []
    for position in range(12):
        run_id = f"{RUN_PREFIX}{position + 1:02d}"
        with connect() as conn:
            found = conn.execute(
                "SELECT id,project_id,flow,status FROM deployment_runs WHERE id=%s",
                (run_id,),
            ).fetchone()
        if found and (
            int(found["project_id"]) != int(own["id"])
            or found["flow"] != FLOW
            or found["status"] != "created"
        ):
            raise RuntimeError(
                f"shipping_seed_run_collision: {run_id}; retain and inspect existing fixture"
            )
        if not found:
            snapshot = dict.fromkeys(RUN_FIELDS)
            snapshot.update(
                id=run_id,
                project=own["slug"],
                flow=FLOW,
                status="created",
                current_stage="deploy",
                release_lineage=LINEAGE,
                created_at=utc_now(),
                created_by="Shipping review fixture",
                carried_work={
                    "schema": 3,
                    "items": [],
                    "commits": [],
                    "derivation": {"status": "derived", "contents_known": True},
                },
                bound_sources={
                    "schema": 1,
                    "inputs": {},
                    "projects": [
                        {
                            "project": other["slug"],
                            "project_id": int(other["id"]),
                            "commit_sha": LINEAGE,
                        }
                    ],
                },
            )
            project_snapshot(snapshot)
        for member in members:
            with connect() as conn:
                attached = conn.execute(
                    "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
                    (run_id, member["item_id"]),
                ).fetchone()
            if not attached:
                cmd_add_item(run_id, member["item_id"])
        ids.append(run_id)
    return ids
