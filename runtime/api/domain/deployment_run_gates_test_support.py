# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)

from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)

from yoke_core.domain.actors import first_human_actor_id, seed_system_actor

from yoke_core.domain.deployment_run_gates import run_gates

from yoke_core.domain.deployment_run_list_read import list_deployment_runs

from yoke_core.domain.qa_catalog_schema import create_qa_catalog_tables

from yoke_core.domain.qa_review_requests import ensure_qa_review_request

RUN_ID = "run-gate-proof"


def _seed_run_awaiting_approval(conn) -> tuple[int, int]:
    """A run suspended on a prod approval its project owner may answer."""
    conn.execute(
        "INSERT INTO sites(project_id, name, created_at) "
        "VALUES (1, 'Gate test site', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', '2026-07-26T00:00:00Z' FROM sites "
        "WHERE project_id=1 AND name='Gate test site' "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    environment_id = int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='prod'"
        ).fetchone()[0]
    )
    owner = first_human_actor_id(conn)
    originator = seed_system_actor(conn, "gate-originator")
    role = int(
        conn.execute(
            "INSERT INTO roles (id, name, description, created_at) "
            "VALUES (9401, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
            "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
            "RETURNING id"
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') ON CONFLICT DO NOTHING",
        (owner, role),
    )
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, name, stages, created_at) "
        "VALUES ('gate-proof', 1, 'Gate proof', "
        '\'[{"name":"approve-prod","step_runner":"human-approval",'
        '"approvals":{"roles":["owner"],"actors":[]}}]\', '
        "'2026-07-26T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "release_lineage, status, current_stage, created_at) "
        "VALUES (%s, 1, 'gate-proof', 'persistent', %s, 'lineage-gate-proof', "
        "'executing', 'approve-prod', '2026-07-26T00:00:00Z')",
        (RUN_ID, environment_id),
    )
    conn.commit()
    evaluate_deployment_stage_approval(
        conn,
        run_id=RUN_ID,
        stage="approve-prod",
        originator_actor_id=originator,
    )
    conn.commit()
    return owner, originator
