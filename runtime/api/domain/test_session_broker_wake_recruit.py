"""Broker recruitment skips live relays and prefers CLI workers."""

from __future__ import annotations

from datetime import timedelta

from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_recruit import broker_surface_is_worker
from runtime.api.domain.test_session_broker_wake import (
    MACHINE_ID,
    NOW,
    _seed,
    _stamp,
)


def _add_cli_worker(conn, session_id: str = "worker-cli") -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor,executor_surface,executor_version,"
        "machine_id,execution_lane,last_heartbeat,last_tool_call_at,offered_at,"
        "turn_posture,turn_posture_at) VALUES "
        "(?,1,'codex','codex-cli','0.148.0a15',?,'direct',?,?,?,"
        "'running',?)",
        (session_id, MACHINE_ID, _stamp(), _stamp(), _stamp(), _stamp()),
    )
    conn.commit()


def test_worker_surface_is_cli_not_desktop() -> None:
    assert broker_surface_is_worker("codex-cli")
    assert broker_surface_is_worker("cursor-cli")
    assert not broker_surface_is_worker("codex-desktop")
    assert not broker_surface_is_worker("cursor-desktop")
    assert not broker_surface_is_worker(None)


def test_desktop_defers_when_cli_worker_is_available() -> None:
    conn, _message_id = _seed()
    _add_cli_worker(conn)
    assert (
        lease_broker_wake_for_hook(
            conn,
            broker_session_id="broker-a",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=1),
        )
        is None
    )


def test_cli_worker_is_recruited_ahead_of_desktop() -> None:
    conn, _message_id = _seed()
    _add_cli_worker(conn)
    lease = lease_broker_wake_for_hook(
        conn,
        broker_session_id="worker-cli",
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=1),
    )
    assert lease is not None
    assert (
        conn.execute(
            "SELECT broker_session_id FROM session_message_attempts"
        ).fetchone()[0]
        == "worker-cli"
    )


def test_ended_cli_worker_does_not_block_desktop() -> None:
    conn, _message_id = _seed()
    _add_cli_worker(conn)
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id='worker-cli'",
        (_stamp(),),
    )
    conn.commit()
    assert (
        lease_broker_wake_for_hook(
            conn,
            broker_session_id="broker-a",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=1),
        )
        is not None
    )
