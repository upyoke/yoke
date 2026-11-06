# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction,
    native_wake_instruction_sha256,
)

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job

from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases

from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    SessionRelayError,
    WakeMode,
)

from yoke_core.domain.session_relay_versions import (
    surface_operation_supported,
    wake_versions_supported,
)

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    relay_connection,
)

MACHINE_ID = "11111111-1111-4111-8111-111111111111"

RELAY_ID = f"machine:{MACHINE_ID}"


def _connection():
    return relay_connection()


def _heartbeat(
    *, confirmed_absent: tuple[str, ...] = (), **versions: str
) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions=versions or {"codex-cli": "0.148.0a15"},
        surface_confirmed_absent=confirmed_absent,
        project_ids=(10,),
    )


def _clock(value: str = NOW):
    return lambda: value


def _add_wake_recipient(
    conn, *, message_id: str = "message-1", session_id="target"
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,launch_origin,"
        "model,offered_at,last_tool_call_at,ended_at,turn_posture) "
        "VALUES (?,10,'codex-cli','0.148.0a15',?,'yoke','gpt-5',?,NULL,?,"
        "'waiting')",
        (
            session_id,
            MACHINE_ID,
            "2026-08-22T10:00:00.000000Z",
            "2026-08-22T10:30:00.000000Z",
        ),
    )
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,"
        "created_at,expires_at) VALUES (?,1,?,'sha256:body','{}',?,?)",
        (
            message_id,
            "Never send this body through the native wake adapter.",
            "2026-08-22T11:00:00.000000Z",
            "2026-08-23T12:00:00.000000Z",
        ),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,"
        "executor_surface,executor_version,machine_id,state,created_at,wake_after) "
        "VALUES (?,?,10,'{}','{}','codex-cli','0.148.0a15',?,"
        "'pending','2026-08-22T11:00:00.000000Z','2026-08-22T11:10:00.000000Z')",
        (message_id, session_id, MACHINE_ID),
    )
    conn.commit()
