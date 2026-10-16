"""Exclusive recipient scopes share immutable messages and authorized reads."""

from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain import actor_permissions as permissions
from yoke_core.domain import session_message_page as pages
from yoke_core.domain import session_message_queries as queries
from yoke_core.domain import session_message_visibility as visibility
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.session_message_receipts import (
    acknowledge_message,
    cancel_message,
)
from yoke_core.domain.session_message_delivery import expire_due_recipients
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import insert_message, message_details
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_message_recipient_scope import owner_key
from yoke_core.domain.session_manual_wake import request_session_wake
from yoke_core.domain.session_recovery_facts import record_native_turn_end
from yoke_core.domain.session_vendor_error_resume import resume_vendor_error_sessions
from runtime.api.domain.test_org_scope_relay_reports import NOW, OLD, MACHINE


@pytest.fixture
def org_world(test_db, monkeypatch):
    conn = test_db
    owner = seed_human_actor(conn, "Message owner")
    reader = seed_human_actor(conn, "Project reader")
    operator = seed_human_actor(conn, "Organization operator")
    org = default_org_id(conn)
    permissions.grant_actor_project_role(
        conn, actor_id=owner, project_id=1, role_name="operator"
    )
    permissions.grant_actor_project_role(
        conn, actor_id=reader, project_id=1, role_name="viewer"
    )
    permissions.grant_actor_org_role(
        conn, actor_id=operator, org_id=org, role_name="operator"
    )
    for sid, project, actor in (
        ("project-sender", 1, owner),
        ("org-sender", None, owner),
        ("project-target", 1, owner),
        ("org-target", None, owner),
        ("foreign-target", None, reader),
    ):
        conn.execute(
            "INSERT INTO harness_sessions(session_id,executor,executor_surface,executor_version,"
            "provider,workspace,project_id,org_id,actor_id,machine_id,last_heartbeat,"
            "last_tool_call_at,turn_posture,offered_at) VALUES "
            "(%s,'codex','codex-cli','0.152.1','openai','/tmp/message-fixture',%s,%s,%s,%s,%s,%s,'running',%s)",
            (
                sid,
                project,
                org if project is None else None,
                actor,
                MACHINE,
                OLD,
                OLD,
                OLD,
            ),
        )
    conn.commit()
    monkeypatch.setattr(pages, "utc_now", lambda: NOW)
    monkeypatch.setattr(queries, "utc_now", lambda: NOW)
    return SimpleNamespace(
        conn=conn, owner=owner, reader=reader, operator=operator, org=org
    )


def send(world, targets=("org-target",), sender="org-sender", key="intent"):
    return send_message(
        world.conn,
        actor_id=world.owner,
        sender_session_id=sender,
        selector=RecipientSelector(session_ids=list(targets)),
        body="Please inspect the latest result and report the outcome.",
        idempotency_key=key,
        now=NOW,
    )


@pytest.mark.parametrize("sender", ["project-sender", "org-sender"])
@pytest.mark.parametrize("target", ["project-target", "org-target"])
def test_sender_recipient_scope_matrix(org_world, sender, target):
    w = org_world
    result = send(w, (target,), sender)
    original = message_details(w.conn, result["message_id"])
    retry = send(w, (target,), sender)
    assert retry["deduplicated"] and retry["message_id"] == result["message_id"]
    assert message_details(w.conn, result["message_id"]) == original
    row = original["recipients"][0]
    assert (row["project_id"], row["org_id"]) == (
        (1, None) if target.startswith("project") else (None, w.org)
    )
    assert (
        original["sender_actor_id"] == w.owner
        and original["sender_session_id"] == sender
    )


def test_mixed_fanout_owners(org_world):
    result = send(org_world, ("project-target", "org-target"))
    rows = message_details(org_world.conn, result["message_id"])["recipients"]
    assert {owner_key(row) for row in rows} == {("project", 1), ("org", org_world.org)}
    assert len(rows) == 2


@pytest.mark.parametrize("action", ["acknowledge", "expire", "cancel"])
def test_org_recipient_ack_expire_cancel(org_world, action):
    w = org_world
    mid = send(w)["message_id"]
    if action == "acknowledge":
        acknowledge_message(w.conn, message_id=mid, session_id="org-target", now=NOW)
        expected = "acknowledged"
    elif action == "expire":
        expire_due_recipients(w.conn, now=NOW + timedelta(days=30))
        expected = "expired"
    else:
        cancel_message(w.conn, message_id=mid, actor_id=w.owner, now=NOW)
        expected = "cancelled"
    assert message_details(w.conn, mid)["recipients"][0]["state"] == expected


def test_org_only_message_hidden_from_project_reader(org_world):
    w = org_world
    mid = send(w)["message_id"]
    assert not visibility.message_visible(
        w.conn, mid, actor_id=w.reader, session_id=None
    )
    with pytest.raises(SessionMessageError, match="not visible"):
        queries.get_message(w.conn, message_id=mid, actor_id=w.reader, session_id=None)
    page = pages.read_message_page(w.conn, actor_id=w.reader, caller_session_id=None)
    assert not page["messages"]


@pytest.mark.parametrize("actor", ["owner", "operator"])
def test_org_message_visible_to_recipient_actor_and_org_operator(org_world, actor):
    w = org_world
    mid = engine_notice(w)[0]["message_id"]
    actor_id = getattr(w, actor)
    assert visibility.message_visible(w.conn, mid, actor_id=actor_id, session_id=None)
    assert (
        queries.get_message(w.conn, message_id=mid, actor_id=actor_id, session_id=None)[
            "message_id"
        ]
        == mid
    )


def test_org_recipient_history_visibility_no_leak(org_world):
    w = org_world
    mid = send(w, ("org-target", "project-target"))["message_id"]
    page = pages.read_message_page(
        w.conn, actor_id=w.owner, caller_session_id=None, projects=[], detail="full"
    )
    assert [row["message_id"] for row in page["messages"]] == [mid]
    assert {r["org_id"] for r in page["messages"][0]["recipients"]} == {None, w.org}
    assert not visibility.message_visible(
        w.conn, mid, actor_id=w.reader, session_id=None
    )


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_visibility_clause_without_readable_projects_has_no_empty_in(
    org_world, monkeypatch, backend
):
    w = org_world
    if backend == "postgres":
        mid = engine_notice(w)[0]["message_id"]
        w.conn.execute("DELETE FROM actor_project_roles WHERE actor_id=%s", (w.owner,))
        conn, marker = w.conn, "%s"
    else:
        conn, marker, mid = sqlite3.connect(":memory:"), "?", "only-org"
        conn.executescript(
            "CREATE TABLE session_messages(message_id TEXT,sender_actor_id INTEGER);"
            "CREATE TABLE harness_sessions(session_id TEXT,actor_id INTEGER);"
            "CREATE TABLE session_message_recipients(message_id TEXT,session_id TEXT,project_id INTEGER,org_id INTEGER);"
            "CREATE TABLE actor_message_recipients(message_id TEXT,recipient_kind TEXT,actor_id INTEGER,seat_session_id TEXT,project_id INTEGER);"
            "CREATE TABLE actor_org_roles(actor_id INTEGER,org_id INTEGER);"
        )
        conn.execute("INSERT INTO session_messages VALUES (?,NULL)", (mid,))
        conn.execute("INSERT INTO harness_sessions VALUES ('target',?)", (w.owner,))
        conn.execute(
            "INSERT INTO session_message_recipients VALUES (?,'target',NULL,?)",
            (mid, w.org),
        )
        monkeypatch.setattr(
            visibility, "actor_project_ids_with_permission", lambda *a: []
        )
    try:
        clause, params = visibility.visible_clause(
            conn, actor_id=w.owner, caller_session_id=None
        )
        assert "IN ()" not in clause
        assert conn.execute(
            f"SELECT 1 FROM session_messages m WHERE m.message_id={marker} AND {clause}",
            (mid, *params),
        ).fetchone()
    finally:
        if backend == "sqlite":
            conn.close()


def engine_notice(w, *, sender_session_id=None):
    recipients = resolve_recipients(
        w.conn, RecipientSelector(session_ids=["org-target"]), actor_id=w.owner, now=NOW
    )
    options = dict(
        sender_actor_id=None,
        sender_session_id=sender_session_id,
        sender_surface=None,
        body="Engine notice for the recipient.",
        selector_snapshot={},
        idempotency_key="engine",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        recipients=recipients,
        actor_recipients=[],
        wake_after_by_owner={("org", w.org): NOW},
    )
    return insert_message(w.conn, **options)


def test_engine_notice_null_sender_to_org_recipient(org_world):
    w = org_world
    details, created = engine_notice(w)
    again, repeated = engine_notice(w)
    assert created and not repeated and details["message_id"] == again["message_id"]
    assert (
        details["sender_actor_id"] is None
        and details["recipients"][0]["org_id"] == w.org
    )


def relay(world):
    world.conn.execute(
        "INSERT INTO session_relays(relay_id,actor_id,machine_id,hostname,surface_versions,"
        "project_checkouts,first_seen_at,last_seen_at,connected_until,state) "
        "VALUES ('org-relay',%s,%s,'host',%s,'[]',%s,%s,%s,'active')",
        (
            world.owner,
            MACHINE,
            json.dumps({"codex-cli": "0.152.1", "claude-cli": "2.1.238"}),
            OLD,
            NOW,
            NOW + timedelta(hours=1),
        ),
    )
    world.conn.commit()


def test_manual_wake_org_recipient(org_world):
    w = org_world
    relay(w)
    w.conn.execute(
        "UPDATE harness_sessions SET executor='claude-code',executor_surface='claude-vscode',"
        "executor_version='2.1.238',provider='anthropic' WHERE session_id='org-target'"
    )
    result = request_session_wake(
        w.conn,
        actor_id=w.owner,
        caller_session_id="org-sender",
        session_id="org-target",
        public_ref=None,
        prompt=None,
        now=NOW,
    )
    assert result["result_code"] == "queued"
    assert result["evidence"]["wake_interface"] == "supported"
    receipt = message_details(w.conn, result["message_id"])["recipients"][0]
    assert receipt["project_id"] is None and receipt["org_id"] == w.org
    assert receipt["routing_snapshot"]["authorized_project_ids"] == []


def test_vendor_error_resume_org_session_end_to_end(org_world):
    w = org_world
    relay(w)
    record_native_turn_end(
        w.conn,
        "org-target",
        observation={
            "observed_at": (OLD + timedelta(minutes=1)).isoformat(),
            "error_message": "unexpected status 404 Not Found",
            "codex_error_info": "other",
        },
        recorded_at=OLD + timedelta(minutes=1),
    )
    w.conn.commit()
    result = resume_vendor_error_sessions(
        w.conn,
        machine_id=MACHINE,
        authorized_projects=[],
        actor_id=w.owner,
        now=NOW,
    )
    assert result["resumed"] == ["org-target"] and not result["refused"]
    assert (
        w.conn.execute(
            "SELECT vendor_resume_attempts FROM harness_sessions WHERE session_id='org-target'"
        ).fetchone()[0]
        == 1
    )
    rows = w.conn.execute(
        "SELECT r.project_id,r.org_id,r.state,m.sender_actor_id FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id WHERE r.session_id='org-target'"
    ).fetchall()
    assert len(rows) == 1 and tuple(rows[0]) == (None, w.org, "pending", w.owner)
