"""Execution-context reads preserve current member intent and snapshots."""

from __future__ import annotations

import json
from typing import Any

import pytest


from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.handlers.deployment_run_execution import _member_rows


def _flow(conn: Any, flow_id: str) -> None:
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps(
            [{"name": "deploy", "stage_kind": "execution", "step_runner": "auto"}]
        ),
        status="active",
    )


def _run(conn: Any, run_id: str, flow_id: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "VALUES (%s,1,%s,'created',%s)",
        (run_id, flow_id, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


def _add_member(
    conn: Any,
    run_id: str,
    item_id: int,
    *,
    delivery_intent: str,
    requirement_snapshot: str,
) -> None:
    conn.execute(
        "INSERT INTO deployment_run_items"
        "(run_id,item_id,added_at,delivery_intent,requirement_snapshot) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            run_id,
            item_id,
            "2026-09-14T00:00:00Z",
            delivery_intent,
            requirement_snapshot,
        ),
    )
    conn.commit()


@pytest.fixture()
def test_db():
    with pg_testdb.test_database() as conn:
        yield conn


def test_empty_membership(test_db: Any) -> None:
    _flow(test_db, "flow-empty")
    _run(test_db, "run-empty", "flow-empty")

    assert _member_rows("run-empty") == []


def test_populated_membership(test_db: Any) -> None:
    _flow(test_db, "flow-populated")
    _run(test_db, "run-populated", "flow-populated")
    insert_item(test_db, id=9501, workflow_id="dash", status="implementing")
    snapshot = json.dumps({"requirements": []})
    _add_member(
        test_db,
        "run-populated",
        9501,
        delivery_intent="final",
        requirement_snapshot=snapshot,
    )

    members = _member_rows("run-populated")

    assert len(members) == 1
    assert members[0]["public_ref"] == "YOK-9501"
    assert members[0]["delivery_intent"] == "final"
    assert members[0]["requirement_snapshot"] == snapshot
