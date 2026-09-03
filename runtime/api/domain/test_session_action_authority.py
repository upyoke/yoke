"""One role check decides what a caller may do to another actor's session."""

from __future__ import annotations

import sqlite3

from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_WRITE,
    PERM_PROJECT_ADMIN,
    ROLE_OWNER,
    grant_actor_project_role,
)
from yoke_core.domain.session_action_authority import (
    authorize_session_action,
    held_role_names,
    session_is_launched,
)
from runtime.api.domain.test_session_message_support import NOW_TEXT, message_connection


MESSAGE = "session_control.message.send"
WAKE = "session_control.session.wake"
TERMINATE = "session_control.session.terminate"
KEEPALIVE = "session_control.keepalive.hold"

OPERATOR_ACTOR = 10
VIEWER_ACTOR = 11
ORG_ADMIN_ACTOR = 12
UNGRANTED_ACTOR = 13


def _session_row(conn: sqlite3.Connection, session_id: str) -> dict:
    row = conn.execute(
        "SELECT session_id, project_id, actor_id FROM harness_sessions "
        "WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return dict(row)


def _add_interactive_session(
    conn: sqlite3.Connection, session_id: str, actor_id: int
) -> dict:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id,project_id,actor_id,executor,executor_surface,"
        "execution_lane,last_heartbeat,offered_at"
        ") VALUES (?,1,?,'claude-code','claude-desktop','direct',?,?)",
        (session_id, actor_id, NOW_TEXT, NOW_TEXT),
    )
    conn.commit()
    return _session_row(conn, session_id)


def _add_launched_session(
    conn: sqlite3.Connection, session_id: str, actor_id: int
) -> dict:
    target = _add_interactive_session(conn, session_id, actor_id)
    conn.execute(
        "INSERT INTO session_messages ("
        "message_id,sender_actor_id,body,body_sha256,selector_snapshot,"
        "created_at,expires_at"
        ") VALUES ('m-launch',?,'go','sha','{}',?,?)",
        (actor_id, NOW_TEXT, NOW_TEXT),
    )
    conn.execute(
        "INSERT INTO session_launches ("
        "launch_id,requester_actor_id,project_id,requested_surface,"
        "selected_surface,message_id,registered_session_id,deadline_at,created_at"
        ") VALUES ('L-1',?,1,'claude-cli','claude-cli','m-launch',?,?,?)",
        (actor_id, session_id, NOW_TEXT, NOW_TEXT),
    )
    conn.commit()
    return target


def test_project_member_may_message_wake_and_hold_another_session() -> None:
    conn = message_connection()
    target = _session_row(conn, "s1")
    for function_id in (MESSAGE, WAKE, KEEPALIVE):
        decision = authorize_session_action(
            conn,
            actor_id=OPERATOR_ACTOR,
            function_id=function_id,
            project_id=1,
            target=target,
        )
        assert decision.allowed is True, function_id
        assert decision.permission_key == PERM_ITEMS_WRITE


def test_viewer_refusal_names_actor_role_and_action() -> None:
    conn = message_connection()
    decision = authorize_session_action(
        conn,
        actor_id=VIEWER_ACTOR,
        function_id=WAKE,
        project_id=1,
        target=_session_row(conn, "s1"),
    )
    assert decision.allowed is False
    assert decision.action == "wake"
    assert f"actor {VIEWER_ACTOR}" in decision.message
    assert "viewer" in decision.message
    assert "wake" in decision.message
    assert PERM_ITEMS_WRITE in decision.message


def test_ungranted_actor_refusal_says_no_role() -> None:
    conn = message_connection()
    decision = authorize_session_action(
        conn,
        actor_id=UNGRANTED_ACTOR,
        function_id=MESSAGE,
        project_id=1,
        target=_session_row(conn, "s1"),
    )
    assert decision.allowed is False
    assert "no role" in decision.message


def test_member_may_not_terminate_another_actors_interactive_session() -> None:
    conn = message_connection()
    target = _add_interactive_session(conn, "s-interactive", VIEWER_ACTOR)
    decision = authorize_session_action(
        conn,
        actor_id=OPERATOR_ACTOR,
        function_id=TERMINATE,
        project_id=1,
        target=target,
    )
    assert decision.allowed is False
    assert decision.permission_key == PERM_PROJECT_ADMIN
    assert "terminate" in decision.message
    assert "operator" in decision.message


def test_owner_may_terminate_another_actors_interactive_session() -> None:
    conn = message_connection()
    target = _add_interactive_session(conn, "s-interactive", VIEWER_ACTOR)
    grant_actor_project_role(
        conn, actor_id=OPERATOR_ACTOR, project_id=1, role_name=ROLE_OWNER
    )
    decision = authorize_session_action(
        conn,
        actor_id=OPERATOR_ACTOR,
        function_id=TERMINATE,
        project_id=1,
        target=target,
    )
    assert decision.allowed is True
    assert decision.permission_key == PERM_PROJECT_ADMIN


def test_org_admin_may_terminate_another_actors_interactive_session() -> None:
    conn = message_connection()
    target = _add_interactive_session(conn, "s-interactive", VIEWER_ACTOR)
    decision = authorize_session_action(
        conn,
        actor_id=ORG_ADMIN_ACTOR,
        function_id=TERMINATE,
        project_id=1,
        target=target,
    )
    assert decision.allowed is True


def test_member_may_terminate_a_launched_worker() -> None:
    conn = message_connection()
    target = _add_launched_session(conn, "s-worker", VIEWER_ACTOR)
    assert session_is_launched(conn, "s-worker") is True
    decision = authorize_session_action(
        conn,
        actor_id=OPERATOR_ACTOR,
        function_id=TERMINATE,
        project_id=1,
        target=target,
    )
    assert decision.allowed is True
    assert decision.permission_key == PERM_ITEMS_WRITE


def test_member_may_terminate_its_own_interactive_session() -> None:
    conn = message_connection()
    decision = authorize_session_action(
        conn,
        actor_id=OPERATOR_ACTOR,
        function_id=TERMINATE,
        project_id=1,
        target=_session_row(conn, "s1"),
    )
    assert decision.allowed is True
    assert decision.permission_key == PERM_ITEMS_WRITE


def test_held_role_names_reports_project_and_org_grants() -> None:
    conn = message_connection()
    assert held_role_names(conn, actor_id=VIEWER_ACTOR, project_id=1) == ("viewer",)
    assert held_role_names(conn, actor_id=ORG_ADMIN_ACTOR, project_id=1) == ("admin",)
    assert held_role_names(conn, actor_id=UNGRANTED_ACTOR, project_id=1) == ()
