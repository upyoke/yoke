# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import timedelta

import pytest

from yoke_contracts.timestamps import format_instant

from yoke_core.domain.session_message_service import send_message

from yoke_core.domain.session_message_store import message_details, public_recipients

from yoke_core.domain.session_message_wake import wake_eligible_recipients

from yoke_core.domain.session_control_roster import session_control_roster_result

from yoke_core.domain.session_relay import claim_relay_job

from yoke_core.domain.session_relay_types import RelayHeartbeat

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)

MACHINE_ID = "22222222-2222-4222-8222-222222222222"

RELAY_ID = f"machine:{MACHINE_ID}"

WAKE_TIME = "2026-08-22T16:11:00Z"

STALE_ACTIVITY = format_instant(NOW - timedelta(minutes=120))


def _surface_connection(*, executor: str, surface: str, version: str, ended: bool):
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor=?,executor_surface=?,"
        "executor_version=?,machine_id=?,last_heartbeat=?,last_tool_call_at=?,"
        "turn_posture=?,ended_at=? WHERE session_id='s2'",
        (
            executor,
            surface,
            version,
            MACHINE_ID,
            NOW_TEXT if ended else STALE_ACTIVITY,
            NOW_TEXT if ended else STALE_ACTIVITY,
            "waiting" if ended else "running",
            NOW_TEXT if ended else None,
        ),
    )
    conn.commit()
    return conn


def _register_relay(conn, surface_versions: dict[str, str]) -> None:
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state) VALUES (?,?,?,?,?,?,?,?,?,?,'active')",
        (
            RELAY_ID,
            10,
            MACHINE_ID,
            "dev-relay",
            "0.1.1",
            json.dumps(surface_versions),
            json.dumps([1]),
            NOW_TEXT,
            NOW_TEXT,
            "2026-08-23T00:00:00Z",
        ),
    )
    conn.commit()


def _heartbeat(surface_versions: dict[str, str]) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="dev-relay",
        relay_version="0.1.1",
        surface_versions=dict(surface_versions),
        project_ids=(1,),
    )


def _send(conn) -> str:
    return str(
        send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s2"]),
            body="Body stays server-side through every wake route.",
            now=NOW,
        )["message_id"]
    )


def _snapshot_route(conn, message_id: str) -> dict:
    recipient = public_recipients(message_details(conn, message_id))[0]
    return dict(recipient["messageability"])
