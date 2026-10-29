"""Retirement preserves history and refuses unresolved project obligations."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run

import json
import re

import pytest

from runtime.api.fixtures.file_test_db import init_test_db, apply_test_schema
from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import render_item_ref
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
    with init_test_db(tmp_path, apply_schema=apply_test_schema):
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
    assert resolve_session_project_scope(conn, override=["fixture"]) == []


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
        conn,
        id=300,
        project_sequence=17,
        workflow_id="dash",
        project="fixture",
        status="implementing",
    )
    item_ref = render_item_ref(conn, 300)
    with pytest.raises(
        ProjectRetirementError, match=re.escape(f"open item {item_ref}")
    ) as error:
        retire(conn)
    assert error.value.code == "project_retirement_blocked"
    assert "then retry" in str(error.value)
    assert (
        conn.execute("SELECT retired_at FROM projects WHERE id=30").fetchone()[0]
        is None
    )


@pytest.mark.parametrize("status", ["created", "executing"])
def test_in_flight_deployment_refuses(conn, status):
    insert_deployment_run(
        conn,
        id="run-1",
        project_id=30,
        flow="fixture-flow",
        status=status,
        created_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(
        ProjectRetirementError, match=f"deployment run run-1 \\({status}\\)"
    ):
        retire(conn)


@pytest.mark.parametrize(
    "kind,scope",
    [
        ("steering", {"project_id": 30}),
        (
            "migration_serialization",
            {"project_id": 30, "model": "core", "item_id": 300},
        ),
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
    with pytest.raises(ProjectRetirementError, match=f"held {kind} claim") as error:
        retire(conn)
    claim_id = conn.execute("SELECT id FROM work_claims").fetchone()[0]
    assert "(holder session owner)" in str(error.value)
    assert f"yoke claims work release --claim-id {claim_id} " in str(error.value)
    assert "terminate" not in str(error.value)
    conn.execute("UPDATE work_claims SET released_at='2026-01-02'")
    assert retire(conn)["retired_at"]


def test_named_release_recovery_frees_an_ended_holder(conn):
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session
    from yoke_core.domain.sessions_lifecycle_claim import release_claim
    from yoke_core.domain.work_claim_targets import (
        make_item_target,
        make_steering_target,
    )

    insert_item(conn, id=300, workflow_id="dash", project="fixture", status="done")
    for sid in ("owner", "steerer"):
        seed_qa_session(conn, sid)
    conn.execute(
        "UPDATE harness_sessions SET project_id=30, ended_at='2026-01-02' "
        "WHERE session_id='owner'"
    )
    for sid, target in (
        ("owner", make_item_target(300)),
        ("steerer", make_steering_target(1)),
    ):
        conn.execute(
            "INSERT INTO work_claims (session_id,target_kind,scope,claim_type,"
            "claimed_at,last_heartbeat) "
            "VALUES (%s,%s,%s,'exclusive','2026-01-01','2026-01-01')",
            (sid, target.kind, target.scope_json()),
        )
    with pytest.raises(ProjectRetirementError) as error:
        retire(conn)
    claim_id = conn.execute(
        "SELECT id FROM work_claims WHERE session_id='owner'"
    ).fetchone()[0]
    assert f"yoke claims work release --claim-id {claim_id} " in str(error.value)
    release_claim(conn, claim_id, reason="claims abandoned by an ended session")
    assert retire(conn)["retired_at"]
    holder = conn.execute(
        "SELECT terminated_at FROM harness_sessions WHERE session_id='owner'"
    ).fetchone()[0]
    assert holder is None


def test_preconvergence_lists_preserve_inventory_and_writer_refuses(conn):
    conn.execute("ALTER TABLE projects DROP COLUMN retired_at")
    assert active_projects_where(conn) == ""
    with pytest.raises(ProjectRetirementError, match="boot convergence") as error:
        retire(conn)
    assert error.value.code == "project_retirement_schema_unavailable"


@pytest.mark.parametrize(
    "function_id",
    [
        "items.create",
        "items.update",
        "items.structured_field.replace",
        "claims.work.acquire",
        "session_control.launch.create",
        "deployment_runs.create",
    ],
)
def test_retired_project_write_admission_names_recovery(conn, function_id):
    from types import SimpleNamespace
    from yoke_contracts.api.function_call import FunctionCallRequest
    from yoke_core.domain.project_write_retirement import check_retirement
    from yoke_core.domain.yoke_function_permission_types import DispatchPermission

    retire(conn)
    entry = SimpleNamespace(
        function_id=function_id, version="v1", side_effects=("write",)
    )
    request = FunctionCallRequest(
        function=function_id,
        actor={"session_id": "test-session"},
        target={"kind": "global", "project_id": "30"},
    )
    denied = check_retirement(
        conn, entry, request, DispatchPermission(None, 30, "fixture")
    )
    assert denied.error.error.code == "project_retired"
    assert "yoke projects unretire --project 30" in denied.error.error.message
    set_retirement(conn, "fixture", retired=False, reason="resume work")
    assert (
        check_retirement(
            conn, entry, request, DispatchPermission(None, 30, "fixture")
        ).error
        is None
    )


def test_upkeep_and_explicit_watcher_scope_skip_retired_project(conn, monkeypatch):
    from yoke_core.domain import control_plane_upkeep

    retire(conn)
    seen = []

    def observe(_conn, projects, **kwargs):
        seen.extend(projects)
        return {}

    monkeypatch.setattr(control_plane_upkeep, "observe_pending_landings", observe)
    monkeypatch.setattr(control_plane_upkeep, "observe_pending_ci_runs", observe)
    control_plane_upkeep.observe_pending_github_work(conn)
    assert 30 not in seen
    assert resolve_session_project_scope(conn, override=["fixture"]) == []


def test_retired_project_webhook_does_not_touch_binding(conn):
    from yoke_core.domain.project_github_binding_lifecycle import (
        cmd_apply_project_github_binding_lifecycle,
    )

    retire(conn)
    result = cmd_apply_project_github_binding_lifecycle(
        "fixture",
        installation_id="1",
        repository_id="2",
        installation_status="active",
        repository_available=True,
        conn=conn,
    )
    assert result == {"project_id": 30, "skipped": "project_retired"}
