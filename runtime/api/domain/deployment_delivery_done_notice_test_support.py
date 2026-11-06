# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_org_role, seed_project_role

import json

from typing import Any

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    SESSION_ACTOR_ID,
    _claim,
    _project,
    seed_session,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OWNER,
)

from yoke_core.domain.deployment_delivery_done_notice import (
    delivery_done_idempotency_key,
    notify_delivery_done,
)

from yoke_core.domain.deployment_flow_versioning import cmd_create

from yoke_core.domain.work_claim_targets import make_item_target

LINEAGE = "d" * 40

OWNER_ACTOR_ID = 9901


def _owner(conn: Any, project_id: int = 1) -> int:
    """A human member of the project, distinct from the claim holder's actor."""
    conn.execute(
        "INSERT INTO actors(id,kind,name,created_at) VALUES "
        "(%s,'human','Release Owner','2026-09-14T00:00:00Z') "
        "ON CONFLICT(id) DO NOTHING",
        (OWNER_ACTOR_ID,),
    )
    seed_project_role(
        conn,
        actor_id=OWNER_ACTOR_ID,
        project_id=project_id,
        role_name=ROLE_OWNER,
    )
    # Addressing a human member resolves through shared organization
    # membership, so the owner needs its org role too.
    for org_id in _org_ids(conn, project_id):
        seed_org_role(
            conn, actor_id=OWNER_ACTOR_ID, org_id=org_id, role_name=ROLE_ADMIN
        )
    conn.commit()
    return OWNER_ACTOR_ID


def _org_ids(conn: Any, project_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT org_id FROM projects WHERE id=%s", (int(project_id),)
    ).fetchall()
    return [int(row["org_id"]) for row in rows if row["org_id"] is not None]


def _environment(conn: Any) -> int:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'stage','https://stage.example.test','{}',%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        ("2026-09-14T00:00:00Z",),
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='stage'"
        ).fetchone()["id"]
    )


def _run(
    conn: Any,
    run_id: str,
    item_id: int,
    *,
    status: str = "succeeded",
    intent: str = "final",
    target_tier: str = "persistent",
    with_environment: bool = True,
    observed_target: str = "",
) -> None:
    environment_id = _environment(conn) if with_environment else None
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps(
            [{"name": "deploy", "stage_kind": "execution", "step_runner": "auto"}]
        ),
        status="disabled",
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "target_tier,target_environment_id,current_stage,created_at,completed_at) "
        "VALUES (%s,1,%s,%s,%s,%s,%s,'complete',%s,%s)",
        (
            run_id,
            flow_id,
            LINEAGE,
            status,
            target_tier,
            environment_id,
            "2026-09-14T00:00:00Z",
            "2026-09-14T00:05:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,delivery_intent) "
        "VALUES (%s,%s,%s,%s)",
        (run_id, item_id, "2026-09-14T00:00:00Z", intent),
    )
    if observed_target:
        conn.execute(
            "INSERT INTO deployment_stage_receipts(run_id,stage_name,"
            "attempt_number,correlation_id,target_kind,target_name,status,"
            "observed_release_lineage,executor,created_at,completed_at) VALUES "
            "(%s,'deploy',1,%s,'persistent_environment',%s,'ready',%s,'test',"
            "%s,%s)",
            (
                run_id,
                f"{run_id}-deploy-1",
                observed_target,
                LINEAGE,
                "2026-09-14T00:00:00Z",
                "2026-09-14T00:04:00Z",
            ),
        )
    conn.commit()


def _inbox(conn: Any, idempotency_key: str) -> list[tuple[int, str]]:
    """Every human-Inbox recipient row for one notice, with its body."""
    rows = conn.execute(
        "SELECT r.actor_id, m.body FROM session_messages m "
        "JOIN actor_message_recipients r ON r.message_id = m.message_id "
        "WHERE m.idempotency_key = %s ORDER BY r.actor_id",
        (idempotency_key,),
    ).fetchall()
    return [(int(row["actor_id"]), str(row["body"])) for row in rows]
