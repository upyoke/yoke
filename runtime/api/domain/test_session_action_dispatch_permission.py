"""The dispatcher applies the session-action role check before the handler."""

from __future__ import annotations

import sqlite3

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE, PERM_PROJECT_ADMIN
from yoke_core.domain.session_action_dispatch_permission import (
    session_action_dispatch_permission,
    target_session_row,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry
from runtime.api.domain.test_session_message_support import NOW_TEXT, message_connection


OPERATOR_ACTOR = 10
VIEWER_ACTOR = 11


def _entry(function_id: str) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda request: None,
        request_model=FunctionCallRequest,
        response_model=FunctionCallRequest,
        stability="stable",
        owner_module="test",
        target_kinds=("global",),
        side_effects=("harness_sessions_update",),
        emitted_event_names=("YokeFunctionCalled",),
        guardrails=("verified_actor",),
        adapter_status="live",
    )


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": function_id,
            "actor": {"actor_id": "10", "session_id": "caller"},
            "target": {"kind": "global"},
            "payload": payload,
        }
    )


def _add_interactive_session(
    conn: sqlite3.Connection, session_id: str, actor_id: int
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id,project_id,actor_id,executor,executor_surface,"
        "execution_lane,last_heartbeat,offered_at"
        ") VALUES (?,1,?,'claude-code','claude-desktop','direct',?,?)",
        (session_id, actor_id, NOW_TEXT, NOW_TEXT),
    )
    conn.commit()


def test_a_non_session_action_passes_through_untouched() -> None:
    conn = message_connection()
    permission = session_action_dispatch_permission(
        conn,
        _entry("sessions.touch"),
        _request("sessions.touch", {"mode": "dash"}),
        OPERATOR_ACTOR,
        None,
    )
    assert permission.error is None
    assert permission.project_id is None


def test_a_permitted_wake_records_the_project_it_authorized() -> None:
    conn = message_connection()
    permission = session_action_dispatch_permission(
        conn,
        _entry("session_control.session.wake"),
        _request("session_control.session.wake", {"session_id": "s1"}),
        OPERATOR_ACTOR,
        None,
    )
    assert permission.error is None
    assert permission.project_id == 1
    assert permission.permission_key == PERM_ITEMS_WRITE


def test_terminating_another_actors_interactive_session_is_denied() -> None:
    conn = message_connection()
    _add_interactive_session(conn, "s-interactive", VIEWER_ACTOR)
    permission = session_action_dispatch_permission(
        conn,
        _entry("session_control.session.terminate"),
        _request("session_control.session.terminate", {"session_id": "s-interactive"}),
        OPERATOR_ACTOR,
        None,
    )
    assert permission.error is not None
    assert permission.error.error.code == "permission_denied"
    assert permission.permission_key == PERM_PROJECT_ADMIN
    assert "terminate" in permission.error.error.message
    assert "operator" in permission.error.error.message


def test_an_unknown_target_defers_to_the_handlers_not_found() -> None:
    conn = message_connection()
    permission = session_action_dispatch_permission(
        conn,
        _entry("session_control.session.terminate"),
        _request("session_control.session.terminate", {"session_id": "nobody"}),
        OPERATOR_ACTOR,
        None,
    )
    assert permission.error is None
    assert target_session_row(conn, "nobody") is None


def test_an_anchor_addressed_wake_defers_to_the_handler() -> None:
    conn = message_connection()
    permission = session_action_dispatch_permission(
        conn,
        _entry("session_control.session.wake"),
        _request("session_control.session.wake", {"public_ref": "ALP-1"}),
        OPERATOR_ACTOR,
        None,
    )
    assert permission.error is None
    assert permission.project_id is None
