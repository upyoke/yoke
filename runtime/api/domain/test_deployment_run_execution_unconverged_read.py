"""Execution-context member reads survive deployment_run_items missing additive columns."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain import (
    test_deployment_execution_serving_authority as serving_fixture,
)
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.actor_state import (
    ActorStateRefused,
    actor_is_active,
    set_actor_enabled,
)
from yoke_core.domain.approval_decisions import _holds_role
from yoke_core.domain.decision_request_authority import human_role_holders
from yoke_core.domain.deployment_qa_result_notice import _role_holders
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.handlers.deployment_run_execution import _member_rows
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.workflow_project_defaults import list_approval_actors


serving_plane = serving_fixture.serving_plane
_call = serving_fixture._call
PROJECT = serving_fixture.PROJECT
FLOW = serving_fixture.FLOW
LINEAGE = serving_fixture.LINEAGE
ITEM_ID = serving_fixture.ITEM_ID


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
        (
            run_id,
            item_id,
            "2026-09-14T00:00:00Z",
            delivery_intent,
            requirement_snapshot,
        ),
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
    """A live table missing the additive columns degrades to ``None`` members.

    ``_member_rows`` previously named ``delivery_intent`` /
    ``requirement_snapshot`` unconditionally in its SELECT list, so a table
    that had not yet converged those additive columns raised
    ``UndefinedColumn`` before any row was ever read.
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


def test_execution_context_dispatch_survives_unconverged_columns(
    serving_plane,
) -> None:
    """The dispatched ``deployment_runs.execution.context`` function id,
    not just ``_member_rows`` directly, tolerates the missing columns."""
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]
    conn = serving_plane["conn"]

    created = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["result"]["run_id"]
    _add_member(
        conn,
        run_id,
        ITEM_ID,
        delivery_intent="final",
        requirement_snapshot=json.dumps({"requirements": []}),
    )
    _drop_additive_columns(conn)

    context = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.context",
        run_id=run_id,
    )

    assert context.status_code == 200, context.text
    members = context.json()["result"]["members"]
    assert len(members) == 1
    assert members[0]["item_id"] == ITEM_ID
    assert members[0]["delivery_intent"] is None
    assert members[0]["requirement_snapshot"] is None


def test_deployment_create_and_execution_survive_unconverged_actor_status(
    serving_plane,
) -> None:
    """The admin driver must create its own deploy before server boot converge."""
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]
    actor_id = serving_plane["owner_id"]
    conn = serving_plane["conn"]
    project_id = resolve_project_id(conn, PROJECT)
    conn.execute("ALTER TABLE actors DROP COLUMN status")
    conn.commit()

    assert actor_is_active(conn, actor_id)
    assert not actor_is_active(conn, actor_id + 1000000)
    assert human_role_holders(
        conn, scope_kind="project", scope_id=project_id, role_name="owner"
    ) == (actor_id,)
    assert _holds_role(
        conn,
        actor_id=actor_id,
        scope_kind="project",
        scope_id=project_id,
        role_name="owner",
    )
    assert _role_holders(conn, project_id=project_id, roles=("owner",)) == {actor_id}
    assert actor_id in {row["id"] for row in list_approval_actors(conn)}
    with pytest.raises(ActorStateRefused, match="boot-converge"):
        set_actor_enabled(
            conn,
            actor_id=actor_id,
            caller_actor_id=actor_id,
            enabled=False,
            now="2026-09-25T00:00:00Z",
        )

    created = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["result"]["run_id"]
    started = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "status", "value": "executing"},
    )
    assert started.status_code == 200, started.text
    context = _call(
        client, headers, session_id, "deployment_runs.execution.context", run_id=run_id
    )
    assert context.status_code == 200, context.text
    roster = _call(client, headers, session_id, "actors.roster")
    assert roster.status_code == 200, roster.text
    owner_row = next(
        row for row in roster.json()["result"]["rows"] if row["id"] == actor_id
    )
    assert owner_row["status"] == "active"
