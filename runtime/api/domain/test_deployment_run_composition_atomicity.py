"""Interrupted release admission leaves no partially frozen run state."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item, cmd_update


def _fixture(conn: Any) -> None:
    stages = json.dumps(
        [
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
                "verdict": {"mode": "agent_only"},
            }
        ]
    )
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version) VALUES "
        "('atomic-flow',1,'Atomic flow','',%s,%s,'disabled',2)",
        (stages, "2026-09-14T00:00:00Z"),
    )
    for item_id in (9431, 9432):
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id - 9000,
            workflow_id="blitz",
            status="implementing",
            deployment_flow="atomic-flow",
        )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at,composition_resolution) VALUES "
        "('run-atomic',1,'atomic-flow',%s,'created',%s,'baseline attested')",
        ("a" * 40, "2026-09-14T00:00:00Z"),
    )
    conn.commit()
    cmd_add_item("run-atomic", 9431)
    cmd_add_item("run-atomic", 9432)


def test_interrupted_member_snapshot_rolls_back_the_whole_freeze(
    test_db: Any,
    monkeypatch,
) -> None:
    _fixture(test_db)
    monkeypatch.setattr(
        composition,
        "record_carried_work",
        lambda _conn, _run: {
            "schema": 1,
            "derivation": {"contents_known": True, "reason": "test-fixture"},
            "items": [],
            "commits": [],
        },
    )
    real_snapshot = composition.snapshot_member_requirements
    calls = 0

    def interrupted_snapshot(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("snapshot interrupted")
        return real_snapshot(*args, **kwargs)

    monkeypatch.setattr(
        composition, "snapshot_member_requirements", interrupted_snapshot
    )
    with pytest.raises(RuntimeError, match="snapshot interrupted"):
        cmd_update("run-atomic", "status", "executing")

    run = test_db.execute(
        "SELECT status,composition_frozen_at,requirement_snapshot "
        "FROM deployment_runs WHERE id='run-atomic'"
    ).fetchone()
    assert tuple(run) == ("created", None, None)
    members = test_db.execute(
        "SELECT delivery_intent,requirement_snapshot FROM deployment_run_items "
        "WHERE run_id='run-atomic' ORDER BY item_id"
    ).fetchall()
    assert [tuple(row) for row in members] == [(None, None), (None, None)]
