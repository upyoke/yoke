# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from runtime.api.fixtures.actor_roles import seed_org_role

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

from runtime.api.domain.org_scope_relay_reports_test_support import NOW, OLD, MACHINE


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
    seed_org_role(conn, actor_id=operator, org_id=org, role_name="operator")
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
    conn.execute("UPDATE harness_sessions SET launch_origin='yoke'")
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
