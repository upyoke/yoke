"""Execution-context member reads survive deployment_run_items missing additive columns."""

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
        json.dumps([{"name": "deploy", "step_runner": "auto"}]),
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
        (run_id, item_id, "2026-09-14T00:00:00Z", delivery_intent, requirement_snapshot),
    )
    conn.commit()


def _drop_additive_columns(conn: Any) -> None:
    conn.execute(
        "ALTER TABLE deployment_run_items "
        "DROP COLUMN delivery_intent, "
        "DROP COLUMN requirement_selection, "
        "DROP COLUMN requirement_snapshot"
    )
    conn.commit()


@pytest.fixture()
def test_db():
    with pg_testdb.test_database() as conn:
        yield conn


def test_empty_membership_converged_schema(test_db: Any) -> None:
    _flow(test_db, "flow-empty-converged")
    _run(test_db, "run-empty-converged", "flow-empty-converged")

    assert _member_rows("run-empty-converged") == []


def test_populated_membership_converged_schema(test_db: Any) -> None:
    _flow(test_db, "flow-populated-converged")
    _run(test_db, "run-populated-converged", "flow-populated-converged")
    insert_item(test_db, id=9501, workflow_id="dash", status="implementing")
    snapshot = json.dumps({"requirements": []})
    _add_member(
        test_db,
        "run-populated-converged",
        9501,
        delivery_intent="final",
        requirement_snapshot=snapshot,
    )

    members = _member_rows("run-populated-converged")

    assert len(members) == 1
    assert members[0]["item_id"] == 9501
    assert members[0]["delivery_intent"] == "final"
    assert members[0]["requirement_snapshot"] == snapshot


def test_empty_membership_unconverged_schema(test_db: Any) -> None:
    _flow(test_db, "flow-empty-unconverged")
    _run(test_db, "run-empty-unconverged", "flow-empty-unconverged")
    _drop_additive_columns(test_db)

    assert _member_rows("run-empty-unconverged") == []


def test_populated_membership_unconverged_schema(test_db: Any) -> None:
    """The bootstrap driver's crash before dispatch: FN50113 regression.

    A live table lacking the additive ``delivery_intent`` /
    ``requirement_snapshot`` columns previously made ``_member_rows`` raise
    ``UndefinedColumn`` because the SELECT list named those columns
    unconditionally; the member row now degrades them to ``None`` instead.
    """
    _flow(test_db, "flow-populated-unconverged")
    _run(test_db, "run-populated-unconverged", "flow-populated-unconverged")
    insert_item(test_db, id=9502, workflow_id="dash", status="implementing")
    _add_member(
        test_db,
        "run-populated-unconverged",
        9502,
        delivery_intent="final",
        requirement_snapshot=json.dumps({"requirements": []}),
    )
    _drop_additive_columns(test_db)

    members = _member_rows("run-populated-unconverged")

    assert len(members) == 1
    assert members[0]["item_id"] == 9502
    assert members[0]["delivery_intent"] is None
    assert members[0]["requirement_snapshot"] is None
