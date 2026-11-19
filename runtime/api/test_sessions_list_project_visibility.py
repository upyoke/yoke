"""Explicit session project reads stay within authenticated visibility."""

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.api.main import app
from yoke_core.domain import db_backend
from yoke_core.domain import yoke_function_dispatch as dispatch
from yoke_core.domain import yoke_function_dispatch_events as events
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.actor_permissions import grant_actor_org_role
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.sessions_list_read import list_sessions, session_read_batch
from yoke_core.domain.work_claim_targets import make_steering_target
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(events, "emit_event", lambda *_a, **_k: None)
    monkeypatch.setattr(dispatch, "_idempotency_lookup", lambda *_a, **_k: None)
    reset_registry_for_tests()
    register_all_handlers()
    try:
        with test_database() as conn:
            auth = mint_api_auth_context(conn)
            other_org = conn.execute(
                "INSERT INTO organizations (slug,name,created_at) VALUES "
                "('hidden-org','Hidden organization',now()) RETURNING id"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO projects (id,slug,name,org_id,created_at) VALUES "
                "(81,'hidden-project','Hidden project',%s,now())",
                (other_org,),
            )
            other = seed_human_actor(conn, "Hidden actor")
            for sid, actor, project, org in (
                ("org-owner", auth.actor_id, None, auth.org_id),
                ("visible-session", auth.actor_id, auth.project_id, None),
                ("hidden-session", other, 81, None),
                ("hidden-org", other, None, other_org),
                ("steering-holder", other, 81, None),
            ):
                conn.execute(
                    "INSERT INTO harness_sessions (session_id,actor_id,project_id,"
                    "org_id,executor,provider,workspace,offered_at,last_heartbeat,"
                    "last_tool_call_at,tool_call_count) VALUES "
                    "(%s,%s,%s,%s,'codex','openai','/tmp/sessions',now(),now(),now(),1)",
                    (sid, actor, project, org),
                )
            conn.execute(
                "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,"
                "last_heartbeat,reason) VALUES "
                "('steering-holder','steering',%s,now(),now(),'fixture')",
                (make_steering_target(auth.project_id).scope_json(),),
            )
            conn.commit()
            with TestClient(app) as client:
                client.headers.update(auth.headers)
                yield SimpleNamespace(
                    conn=conn,
                    client=client,
                    owner=auth.actor_id,
                    org=auth.org_id,
                    project=auth.project_id,
                    other=other,
                )
    finally:
        reset_registry_for_tests()


def call(world, *, session="org-owner", **payload):
    response = world.client.post(
        "/v1/functions/call",
        json={
            "function": "sessions.list",
            "version": "v1",
            "actor": {"session_id": session},
            "target": {"kind": "global"},
            "payload": payload,
        },
    )
    return response, response.json()


@pytest.mark.parametrize("project", ["81", "hidden-project"])
@pytest.mark.parametrize("detail", ["summary", "full"])
@pytest.mark.parametrize("authority", ["empty", "disjoint"])
@pytest.mark.parametrize("open_only", [False, True])
def test_hidden_project_ref_is_not_a_read_grant(
    world, project, detail, authority, open_only
):
    if authority == "empty":
        for table in ("actor_project_roles", "actor_org_roles"):
            world.conn.execute(f"DELETE FROM {table} WHERE actor_id=%s", (world.owner,))
        world.conn.commit()
    visible = actor_visible_project_ids(world.conn, world.owner)
    assert 81 not in visible
    assert bool(visible) == (authority == "disjoint")
    before = business_state(world)
    response, body = call(world, project=project, detail=detail, open=open_only)
    if open_only:
        assert body["success"], response.text
        assert body["result"]["rows"] == []
    else:
        assert not body["success"], response.text
        assert body["error"]["code"] == "not_found"
        assert not body.get("result")
    assert "Hidden actor" not in response.text
    assert "hidden-session" not in response.text
    assert business_state(world) == before


def business_state(world):
    return {
        table: [tuple(row) for row in world.conn.execute(query).fetchall()]
        for table, query in (
            (
                "sessions",
                "SELECT session_id,actor_id,project_id,org_id FROM harness_sessions ORDER BY session_id",
            ),
            ("projects", "SELECT id,org_id,slug,name FROM projects ORDER BY id"),
            (
                "project_roles",
                "SELECT actor_id,project_id,role_id FROM actor_project_roles ORDER BY actor_id,project_id,role_id",
            ),
            (
                "org_roles",
                "SELECT actor_id,org_id,role_id FROM actor_org_roles ORDER BY actor_id,org_id,role_id",
            ),
        )
    }


@pytest.mark.parametrize("numeric", [False, True])
@pytest.mark.parametrize("detail", ["summary", "full"])
@pytest.mark.parametrize("open_only", [False, True])
def test_authorized_project_keeps_cross_project_steering_holder(
    world, numeric, detail, open_only
):
    slug = world.conn.execute(
        "SELECT slug FROM projects WHERE id=%s", (world.project,)
    ).fetchone()[0]
    project = str(world.project) if numeric else slug
    before = business_state(world)
    response, body = call(world, project=project, detail=detail, open=open_only)
    assert body["success"], response.text
    rows = body["result"]["rows"]
    assert {row["session_id"] for row in rows} == {"visible-session", "steering-holder"}
    assert all(row["scope_kind"] == "project" for row in rows)
    assert business_state(world) == before


@pytest.mark.parametrize("reader", ["owner", "org-reader", "stranger"])
def test_unfiltered_org_rows_follow_actor_authority(world, reader):
    session = "org-owner"
    if reader != "owner":
        if reader == "org-reader":
            grant_actor_org_role(
                world.conn, actor_id=world.other, org_id=world.org, role_name="viewer"
            )
        token = mint_token(world.conn, actor_id=world.other, name="reader")
        world.conn.commit()
        world.client.headers.update({"Authorization": f"Bearer {token.raw_token}"})
        session = "hidden-session"
    response, body = call(world, session=session, detail="full")
    assert body["success"], response.text
    rows = {row["session_id"]: row for row in body["result"]["rows"]}
    assert ("org-owner" in rows) == (reader != "stranger")
    if reader == "owner":
        assert "hidden-org" not in rows
        assert rows["org-owner"]["project_id"] is None
        assert rows["org-owner"]["org_id"] == world.org


def test_reader_local_authority_and_empty_batch_scope_remain_distinct(world):
    assert "hidden-session" in {
        row["session_id"] for row in list_sessions(project="81", project_ids=None)
    }
    with pytest.raises(LookupError, match="not found"):
        list_sessions(project="81", project_ids=[])
    with (
        db_backend.bound_pg_dsn(db_backend.resolve_pg_dsn()),
        session_read_batch(["hidden-session"]),
    ):
        assert list_sessions(session_id="hidden-session")
        assert list_sessions(session_id="hidden-session", project_ids=[]) == []


def _hold_hidden_work(world):
    """The visible session steers project 81, holds its plan, and focuses its item."""
    from runtime.api.fixtures.backlog import insert_item

    world.conn.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,"
        "last_heartbeat,reason) VALUES "
        "('visible-session','steering',%s,now(),now(),'fixture')",
        (make_steering_target(81).scope_json(),),
    )
    world.conn.execute(
        "INSERT INTO strategy_docs (project_id,slug,content,updated_at) "
        "VALUES (81,'HIDDEN-PLAN','Hidden plan.',now())"
    )
    world.conn.execute(
        "INSERT INTO strategy_doc_claims (id,project_id,strategy_doc_slug,"
        "owner_kind,owner_session_id,registered_at) VALUES "
        "(8101,81,'HIDDEN-PLAN','session','visible-session',now())"
    )
    insert_item(
        world.conn, id=8101, title="Hidden focus item", project="hidden-project"
    )
    world.conn.execute(
        "UPDATE harness_sessions SET current_item_id=8101 "
        "WHERE session_id='visible-session'"
    )
    world.conn.commit()


def _project_ids(row):
    holdings = row.get("holdings") or {}
    entries = [
        *(row.get("claims") or []),
        *(holdings.get("current") or []),
        *(holdings.get("previous") or []),
        *(row.get("holds") or []),
        *((row.get("custody") or {}).get("holds") or []),
    ]
    return {
        entry.get("project_id") or entry.get("item_project_id") for entry in entries
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"open": True},
        {"open": True, "detail": "full"},
        {"detail": "full"},
        {"session_id": "visible-session", "detail": "full"},
    ],
)
def test_a_visible_session_names_no_hidden_claim_holding_or_item(world, payload):
    _hold_hidden_work(world)

    response, body = call(world, **payload)

    assert body["success"], response.text
    rows = {row["session_id"]: row for row in body["result"]["rows"]}
    assert "visible-session" in rows
    row = rows["visible-session"]
    assert 81 not in _project_ids(row)
    assert row.get("current_item") is None
    assert row.get("current_item_title") is None
    served = json.dumps(row)
    for secret in ("HIDDEN-PLAN", "hidden-project", "Hidden focus item"):
        assert secret not in served


def test_a_local_read_keeps_hidden_project_holdings(world):
    _hold_hidden_work(world)
    with (
        db_backend.bound_pg_dsn(db_backend.resolve_pg_dsn()),
        session_read_batch(["visible-session"]),
    ):
        [row] = list_sessions(session_id="visible-session")
    assert 81 in _project_ids(row)
    assert row["current_item_title"] == "Hidden focus item"
