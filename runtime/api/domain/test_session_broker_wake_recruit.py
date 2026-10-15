"""Broker recruitment skips live relays and prefers CLI workers."""

from __future__ import annotations

from datetime import timedelta

from yoke_contracts.timestamps import format_instant

from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_recruit import broker_surface_is_worker
from yoke_core.domain.session_relay_storage import heartbeat_relay
from runtime.api.domain.session_broker_test_support import (
    MACHINE_ID,
    NOW,
    RELAY_ID,
    _heartbeat,
    _seed,
    _stamp,
)


def _add_cli_worker(conn, session_id: str = "worker-cli") -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor,executor_surface,executor_version,"
        "machine_id,execution_level,last_heartbeat,last_tool_call_at,offered_at,"
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


def test_drain_heartbeat_keeps_broker_out_until_relay_really_expires() -> None:
    conn, message_id = _seed()
    _add_cli_worker(conn)
    heartbeat_relay(conn, _heartbeat(), state="active", next_poll_seconds=1, now=NOW)

    assert (
        lease_broker_wake_for_hook(
            conn,
            broker_session_id="worker-cli",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=15),
        )
        is None
    )
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        == 0
    )

    assert (
        lease_broker_wake_for_hook(
            conn,
            broker_session_id="worker-cli",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=121),
        )
        is not None
    )


def test_drain_heartbeat_preserves_longer_active_lease() -> None:
    conn, _message_id = _seed()
    heartbeat_relay(conn, _heartbeat(), state="active", next_poll_seconds=1, now=NOW)
    lease_end = NOW + timedelta(minutes=10)
    conn.execute(
        "UPDATE session_relays SET lease_expires_at=? WHERE relay_id=?",
        (format_instant(lease_end), RELAY_ID),
    )
    conn.commit()

    assert (
        heartbeat_relay(
            conn,
            _heartbeat(),
            state="active",
            next_poll_seconds=1,
            now=NOW + timedelta(seconds=1),
        )
        == lease_end
    )


def test_idle_heartbeat_preserves_longer_poll_horizon() -> None:
    conn, _message_id = _seed()
    assert heartbeat_relay(
        conn,
        _heartbeat(),
        state="idle",
        next_poll_seconds=300,
        now=NOW,
    ) == NOW + timedelta(minutes=10)
