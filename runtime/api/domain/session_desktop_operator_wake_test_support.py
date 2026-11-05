# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
    native_wake_supported,
    surface_wake_authority,
)

from yoke_contracts.session_control.surface_versions import (
    machine_wake_surface,
    surface_operation_supported,
)

from yoke_core.domain.session_relay_versions import wake_versions_supported

from yoke_core.domain.actor_message_recipients import ACTOR_KIND

from yoke_core.domain.session_manual_wake import request_session_wake

from yoke_core.domain.session_message_reads import message_details
from yoke_core.domain.session_message_routing import messageability

from yoke_core.domain.session_message_service import send_message

from yoke_core.domain.session_message_types import SessionMessageError

from yoke_core.domain.session_message_wake import wake_eligible_recipients

from yoke_core.domain.session_operator_wake_notice import notify_operator_to_wake

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)

GRACE = timedelta(seconds=300)

STARVED = NOW + GRACE + timedelta(seconds=1)

CLAUDE_DESKTOP_SESSION_ID = "s-desktop"

CLAUDE_DESKTOP_VERSION = "1.32885.1"


def _add_desktop_session(conn, *, session_id: str = CLAUDE_DESKTOP_SESSION_ID) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id,project_id,actor_id,executor,executor_surface,"
        "harness_title,executor_version,machine_id,execution_level,last_heartbeat,"
        "last_tool_call_at,offered_at) "
        "VALUES (?,1,10,'claude-code','claude-desktop','Desktop plan',?,'m5','direct',?,?,?)",
        (session_id, CLAUDE_DESKTOP_VERSION, NOW_TEXT, NOW_TEXT, NOW_TEXT),
    )
    conn.commit()


def _send_to(conn, session_id: str) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[session_id]),
        body="Read the plan and report what you would change.",
        now=NOW,
    )["message_id"]


def _operator_notices(conn, *, actor_id: int = 10) -> list[str]:
    """Bodies of every notice standing for one operator.

    Project each stored notice without the Inbox wall-clock expiry filter;
    these fixtures live at a fixed simulated ``NOW``.
    """
    rows = conn.execute(
        "SELECT m.message_id FROM actor_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE r.recipient_kind=? AND r.actor_id=? AND r.state='pending' "
        "ORDER BY m.created_at,m.message_id",
        (ACTOR_KIND, actor_id),
    ).fetchall()
    return [message_details(conn, row[0])["body"] for row in rows]


def _go_quiet(conn, session_id: str, *, when) -> None:
    """Fresh heartbeat, no tool call since the send — an unattended window."""
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=? WHERE session_id=?",
        (when.strftime("%Y-%m-%dT%H:%M:%SZ"), session_id),
    )
    conn.commit()
