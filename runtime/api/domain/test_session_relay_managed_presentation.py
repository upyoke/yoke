"""Managed-session presentation lookup tests."""

from __future__ import annotations

from yoke_core.domain.session_relay_managed_presentation import (
    managed_session_presentation,
)
from runtime.api.domain.session_launch_test_support import launch_connection


def test_only_a_registered_yoke_launch_gets_local_only_wake_policy():
    conn = launch_connection()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,model) VALUES (?,?,?,?)",
        ("managed", 10, "claude-cli", "claude-opus"),
    )
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,created_at,expires_at) "
        "VALUES ('message-managed',1,'body','hash','{}','now','later')"
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id,requester_actor_id,project_id,requested_surface,selected_surface,"
        "presentation_preference,session_name,allow_surface_fallback,message_id,state,"
        "registered_session_id,deadline_at,created_at,origin) "
        "VALUES ('launch-managed',1,10,'claude-cli','claude-cli','local','Item: title',"
        "0,'message-managed','succeeded','managed','later','now','operator')"
    )
    conn.commit()

    assert (
        managed_session_presentation(conn, session_id="managed", surface="claude-cli")
        == "local"
    )
    assert (
        managed_session_presentation(
            conn, session_id="operator-opened", surface="claude-cli"
        )
        is None
    )
