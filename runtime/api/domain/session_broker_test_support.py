"""Shared canonical SQLite seed and relay fixtures for peer broker wakes."""

from datetime import timedelta

from yoke_contracts.timestamps import format_instant
from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _stamp(minutes: int = 0, seconds: int = 0) -> str:
    value = NOW + timedelta(minutes=minutes, seconds=seconds)
    return format_instant(value)


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="broker-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(1,),
    )


def _seed(path: str = ":memory:"):
    conn = message_connection(path)
    idle_at = _stamp(minutes=-11)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=?,ended_at=?,last_heartbeat=?,"
        "last_tool_call_at=?,turn_posture='waiting',"
        "turn_posture_at=? WHERE session_id='s4'",
        (
            MACHINE_ID,
            format_instant(NOW_TEXT),
            idle_at,
            idle_at,
            format_instant(NOW_TEXT),
        ),
    )
    for broker in ("broker-a", "broker-b"):
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id,project_id,executor,executor_surface,executor_version,"
            "machine_id,execution_level,last_heartbeat,last_tool_call_at,offered_at,"
            "turn_posture,turn_posture_at) VALUES "
            "(?,1,'codex','codex-desktop','26.818.31338',?,'direct',?,?,?,"
            "'running',?)",
            (broker, MACHINE_ID, *(format_instant(NOW_TEXT) for _ in range(4))),
        )
    conn.commit()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s4"]),
        body="Secret body must never enter broker or native traffic.",
        now=NOW - timedelta(minutes=11),
    )["message_id"]
    return conn, message_id


def _reserve(conn, broker: str = "broker-a"):
    return lease_broker_wake_for_hook(
        conn,
        broker_session_id=broker,
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=1),
    )
