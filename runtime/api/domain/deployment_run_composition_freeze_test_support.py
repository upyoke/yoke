# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

import pytest

from yoke_contracts.timestamps import parse_instant, format_instant

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

from yoke_core.domain import deployment_run_composition_freeze as composition

from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_remove_item,
    cmd_update,
)

from yoke_core.domain.flow_create import cmd_create

from yoke_core.domain.workflow_project_defaults import set_delivery_default

ADVANCED_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": dict(
                kind="persistent_environment", environment="stage", source_stage="stage"
            ),
            "verdict": {"mode": "agent_only"},
        },
    ]
)


def _environment(conn: Any) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) "
        "SELECT id,1,'stage','https://stage.example.test',"
        "'2026-09-14T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    conn.commit()


def _flow(conn: Any, flow_id: str, *, advanced: bool) -> None:
    stages = (
        ADVANCED_STAGES
        if advanced
        else json.dumps(
            [{"name": "deploy", "step_runner": "auto", "stage_kind": "execution"}]
        )
    )
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        stages,
        status="disabled" if advanced else "active",
        takes_delivery_custody=advanced,
    )


def _run(conn: Any, run_id: str, flow_id: str, *, lineage: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,created_at,"
        "composition_resolution) VALUES (%s,1,%s,%s,'created',%s,%s)",
        (
            run_id,
            flow_id,
            lineage,
            "2026-09-14T00:00:00Z",
            "operator confirmed the first governed composition baseline",
        ),
    )
    conn.commit()


def _known_carried(item_id: int) -> dict[str, Any]:
    return {
        "schema": 1,
        "derivation": {"contents_known": True, "reason": "test-fixture"},
        "items": [{"item_id": item_id, "ref": f"YOK-{item_id}", "commit_shas": []}],
        "commits": [],
    }
