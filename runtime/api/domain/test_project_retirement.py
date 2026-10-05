"""Retirement preserves history and refuses unresolved project obligations."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import init_test_db, apply_fixture_schema_ddl
from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers.projects_get import (
    handle_projects_get,
    handle_projects_list,
)
from runtime.api.domain.handlers.projects_handler_test_support import project_request
from yoke_core.domain.project_retirement import (
    ProjectRetirementError,
    active_projects_where,
    set_retirement,
)
from yoke_core.domain.session_project_scope import resolve_session_project_scope
from yoke_core.domain.projects_crud import cmd_list


@pytest.fixture
def conn(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl):
        c = connect()
        c.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
            "VALUES (30, 'fixture', 'Fixture', 'FIX', '2026-01-01')"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS deployment_runs "
            "(id TEXT PRIMARY KEY, project_id INTEGER, status TEXT)"
        )
        c.commit()
        yield c
        c.close()


def retire(conn):
    return set_retirement(conn, "fixture", retired=True, reason="Machine case finished")


def test_retire_unretire_preserves_history_and_records_reason(conn, monkeypatch):
    from yoke_core.domain import events

    calls = []
    monkeypatch.setattr(events, "emit_event", lambda *a, **kw: calls.append((a, kw)))
    insert_item(conn, id=300, workflow_id="dash", project="fixture", status="done")
    result = retire(conn)
    assert result["retired_at"] and result["changed"]
    assert retire(conn)["retired_at"] == result["retired_at"]
    assert len(calls) == 1
    assert calls[0][1]["context"]["reason"] == "Machine case finished"
    assert (
        conn.execute("SELECT COUNT(*) FROM items WHERE project_id=30").fetchone()[0]
        == 1
    )
    restored = set_retirement(conn, "30", retired=False, reason="restore")
    assert restored["retired_at"] is None and restored["changed"]


def test_active_inventory_hides_retired_but_direct_read_remains(conn):
    retire(conn)
    conn.commit()
    assert "fixture" not in cmd_list()
    assert "fixture" in cmd_list(include_retired=True)
    for payload in ({}, {"fields": ["id", "slug"]}, {"include_summary": True}):
        result = handle_projects_list(project_request(payload, "projects.list"))
        assert result.primary_success
        assert all(row["id"] != 30 for row in result.result_payload["rows"])
    all_rows = handle_projects_list(
        project_request({"include_retired": True}, "projects.list")
    )
    assert any(row["id"] == 30 for row in all_rows.result_payload["rows"])
    direct = handle_projects_get(project_request({"project": "fixture"}))
    assert direct.primary_success and direct.result_payload["row"]["id"] == 30
    assert 30 not in resolve_session_project_scope(conn)
    assert resolve_session_project_scope(conn, override=["fixture"]) == [30]


def test_retirement_leaves_transaction_commit_with_the_caller(conn):
    retire(conn)
    conn.rollback()
    assert (
        conn.execute("SELECT retired_at FROM projects WHERE id=30").fetchone()[0]
        is None
    )


def test_retirement_does_not_remove_project_permissions(conn, monkeypatch):
    from types import SimpleNamespace
    from yoke_core.domain import actor_permissions
    from yoke_core.domain.actor_project_visibility import (
        actor_project_ids_with_permission,
    )

    retire(conn)
    seen = []

    def decision(connection, *, actor_id, project_id, permission_key):
        seen.append((actor_id, project_id, permission_key))
        return SimpleNamespace(allowed=project_id == 30)

    monkeypatch.setattr(actor_permissions, "permission_decision", decision)
    assert actor_project_ids_with_permission(conn, 12, "items.read") == {30}
    assert (12, 30, "items.read") in seen


def test_open_item_refusal_uses_pinned_terminal_membership(conn):
    insert_item(
        conn, id=300, workflow_id="dash", project="fixture", status="implementing"
    )
    with pytest.raises(ProjectRetirementError, match="open item 300") as error:
        retire(conn)
    assert error.value.code == "project_retirement_blocked"
    assert "then retry" in str(error.value)
    assert (
        conn.execute("SELECT retired_at FROM projects WHERE id=30").fetchone()[0]
        is None
    )


@pytest.mark.parametrize("status", ["created", "executing"])
def test_in_flight_deployment_refuses(conn, status):
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES ('run-1',30,'fixture-flow',%s,'2026-01-01')",
        (status,),
    )
    with pytest.raises(
        ProjectRetirementError, match=f"deployment run run-1 \\({status}\\)"
    ):
        retire(conn)


@pytest.mark.parametrize(
    "kind,scope",
    [
        ("steering", {"project_id": 30}),
        ("deploy_serialization", {"project_id": 30, "project_slug": "fixture"}),
        ("process", {"process_key": "DO", "conflict_group": "discovery:fixture"}),
        ("item", {"item_id": 300}),
        ("epic_task", {"epic_id": 300, "task_num": 1}),
    ],
)
def test_live_claims_refuse_even_on_terminal_items(conn, kind, scope):
    insert_item(conn, id=300, workflow_id="dash", project="fixture", status="done")
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session

    seed_qa_session(conn, "owner")
    conn.execute("UPDATE harness_sessions SET project_id=30 WHERE session_id='owner'")
    conn.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES ('owner',%s,%s,'exclusive','2026-01-01','2026-01-01')",
        (kind, json.dumps(scope)),
    )
    with pytest.raises(ProjectRetirementError, match=f"held {kind} claim"):
        retire(conn)
    conn.execute("UPDATE work_claims SET released_at='2026-01-02'")
    assert retire(conn)["retired_at"]


def test_preconvergence_lists_preserve_inventory_and_writer_refuses(conn):
    conn.execute("ALTER TABLE projects DROP COLUMN retired_at")
    assert active_projects_where(conn) == ""
    with pytest.raises(ProjectRetirementError, match="boot convergence") as error:
        retire(conn)
    assert error.value.code == "project_retirement_schema_unavailable"
