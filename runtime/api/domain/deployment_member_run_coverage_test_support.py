# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.deployment_item_flow_resolution import membership_closes_item

from yoke_core.domain.deployment_member_run_coverage import (
    inert_membership_notice,
    member_coverage_notice,
    member_run_coverage,
)

from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item

from yoke_core.domain.project_identity import render_item_ref

RUN_SCOPED_STAGES = [
    {"name": "merged", "step_runner": "auto", "stage_kind": "execution"},
    {"name": "warm-up", "step_runner": "warm-up", "stage_kind": "execution"},
    {"name": "complete", "step_runner": "auto", "stage_kind": "execution"},
]

ITEM_SCOPED_STAGES = RUN_SCOPED_STAGES + [
    {
        "name": "item-qa",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
        "target": {
            "kind": "persistent_environment",
            "environment": "prod",
            "source_stage": "warm-up",
        },
        "verdict": {"mode": "agent_only"},
    },
]


def _flow(conn: Any, flow_id: str, stages: list[dict[str, Any]]) -> None:
    """Insert one definition directly.

    The activation validator asks whether a QA target can prove its deployed
    identity, which is a different subject from what a run can do for a
    member, and it refuses the minimal stage list this needs.
    """
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version) VALUES "
        "(%s,1,%s,'',%s,'2026-09-19T00:00:00Z','active',2)",
        (flow_id, flow_id, json.dumps(stages)),
    )


def _run(conn: Any, run_id: str, flow_id: str, *, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id, project_id, flow, release_lineage, status, created_at) "
        "VALUES (%s, %s, %s, 'main', 'created', '2026-09-19T00:00:00Z')",
        (run_id, project_id, flow_id),
    )


def _item(conn: Any, item_id: int, *, flow: str = "") -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id - 9000,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow,
    )
