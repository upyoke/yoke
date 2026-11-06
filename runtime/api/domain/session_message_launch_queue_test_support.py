# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from datetime import timedelta

import pytest

from yoke_core.domain.session_message_delivery import (
    lease_for_hook,
    complete_hook_lease,
)

from yoke_core.domain.session_message_service import send_message, preview_message

from yoke_core.domain.session_message_store import message_details, cancel_message_rows

from yoke_core.domain.session_message_page import read_message_page

from yoke_core.domain.session_message_types import SessionMessageError

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
    pin_message_clocks,
)

from runtime.api.domain.session_launch_assignment_postgres_test_support import (
    admission as admission,
    _session,
    _launch,
    _claim,
)


def world(monkeypatch, *, surface="codex-cli"):
    pin_message_clocks(monkeypatch)
    from yoke_core.domain import session_message_launch_queue

    monkeypatch.setattr(session_message_launch_queue, "utc_now", lambda: NOW)
    conn = message_connection()
    conn.execute("DELETE FROM work_claims WHERE target_kind='item'")
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=? WHERE session_id='s4'",
        (surface,),
    )
    # Launch instruction storage and its queue are the same records as real launches.
    conn.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES ('mandate',10,'Claim item',"
        "'digest','{}',?,?)",
        (NOW_TEXT, (NOW + timedelta(hours=1)).isoformat()),
    )
    conn.execute(
        "INSERT INTO session_launches(launch_id,requester_actor_id,project_id,"
        "requested_surface,selected_surface,item_id,allow_surface_fallback,"
        "message_id,state,deadline_at,created_at,origin) VALUES "
        "('launch',10,1,?,?,101,0,'mandate','assigned',?,?,'steering')",
        (surface, surface, (NOW + timedelta(minutes=10)).isoformat(), NOW_TEXT),
    )
    conn.commit()
    return conn


def send(conn, **kwargs):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id=None,
        selector=selector(public_refs=["ALP-1"]),
        body="Include the scope amendment.",
        now=NOW,
        **kwargs,
    )


def claim(conn, *, session="s4", item=101):
    conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at) "
        "VALUES (?,'item',?,?)",
        (session, json.dumps({"item_id": item}), NOW_TEXT),
    )
    conn.commit()


def register(conn):
    conn.execute(
        "UPDATE session_launches SET registered_session_id='s4',"
        "state='awaiting_registration' WHERE launch_id='launch'"
    )
    conn.commit()
