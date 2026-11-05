# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest import mock

from types import SimpleNamespace

import pytest

from runtime.api.domain.deployment_run_gates_test_support import (
    RUN_ID,
    _seed_run_awaiting_approval,
)

from yoke_core.domain.decision_request_resolution import resolve_decision_request

from yoke_core.domain.decision_request_schema import create_decision_request_tables

from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)

from yoke_core.domain.deployment_run_gates import run_gates

from yoke_core.domain.deployment_run_history_read import read_deployment_run_history

from yoke_core.domain.deployment_run_list_read import list_deployment_runs

from yoke_core.domain.deployment_run_member_approvals import (
    member_approval_blockers,
    resume_after_member_decision,
)

from yoke_core.domain import deployment_run_auto_completion


def _mixed_run(
    conn, *, posture: str = '{"approval_on_done":true}'
) -> tuple[str, int, int, int]:
    create_decision_request_tables(conn)
    yoke_owner, other_actor = _seed_run_awaiting_approval(conn)
    run_id = "run-mixed-item-decision"
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id,project_id,flow,target_tier,target_environment_id,release_lineage,"
        "status,current_stage,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,current_stage,created_at "
        "FROM deployment_runs WHERE id=%s",
        (run_id, RUN_ID),
    )
    platform_id = int(conn.execute("SELECT MAX(id)+1 FROM projects").fetchone()[0])
    conn.execute(
        "INSERT INTO projects(id,slug,name,public_item_prefix,org_id,created_at) "
        "SELECT %s,'platform','Platform','PLAT',org_id,'2026-09-28T00:00:00Z' "
        "FROM projects WHERE id=1",
        (platform_id,),
    )
    owner_role = int(
        conn.execute("SELECT id FROM roles WHERE name='owner'").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO actor_project_roles(actor_id,project_id,role_id,granted_at) "
        "VALUES (%s,%s,%s,'2026-09-28T00:00:00Z')",
        (yoke_owner, platform_id, owner_role),
    )
    version = int(
        conn.execute(
            "SELECT current_version_id FROM workflows WHERE id='dash'"
        ).fetchone()[0]
    )
    item_id = int(
        conn.execute(
            "INSERT INTO items(title,status,priority,created_at,updated_at,source,"
            "owner,project_id,project_sequence,workflow_id,workflow_version_id,"
            "workflow_posture) VALUES ('Platform release member','release','medium',"
            "'2026-09-28T00:00:00Z','2026-09-28T00:00:00Z',%s,%s,%s,1,"
            "'dash',%s,%s) RETURNING id",
            (str(other_actor), str(yoke_owner), platform_id, version, posture),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,delivery_intent,added_at) "
        "VALUES (%s,%s,'final','2026-09-28T00:00:00Z')",
        (run_id, item_id),
    )
    conn.commit()
    return run_id, item_id, yoke_owner, platform_id
