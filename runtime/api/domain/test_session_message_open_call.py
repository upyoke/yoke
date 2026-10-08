"""Automatic wakes wait for a live tool call at every activity age."""

from datetime import timedelta
import pytest
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_manual_wake import request_session_wake
from yoke_core.domain.session_staleness import activity_liveness
from runtime.api.domain.test_session_message_support import (
    NOW as MESSAGE_NOW,
    NATIVE_WAKE_SESSION_ID,
    message_connection,
    record_process_gone,
    selector,
)

SURFACES = [
    ("codex", "codex-cli", "0.148.0a15", False),
    ("cursor", "cursor-cli", "2026.08.11", True),
    ("claude-code", "claude-cli", "2.1.238", True),
    ("codex", "codex-desktop", "26.814.41407", False),
    ("cursor", "cursor-desktop", "3.17.8", False),
    ("claude-code", "claude-desktop", "1.32885.1", False),
]
SWEEP = MESSAGE_NOW + timedelta(minutes=40)


@pytest.fixture
def wake_connection(request, monkeypatch):
    from yoke_core.domain import session_staleness

    monkeypatch.setattr(session_staleness, "_resolve_effective_ttl", lambda *args: 20)
    conn = message_connection()
    executor, surface, version, idle_supported = request.param
    conn.execute(
        "UPDATE harness_sessions SET executor=?,executor_surface=?,executor_version=?,"
        "turn_posture='running' WHERE session_id=?",
        (executor, surface, version, NATIVE_WAKE_SESSION_ID),
    )
    conn.executescript(
        "CREATE TABLE session_tool_calls (id INTEGER PRIMARY KEY, session_id TEXT, "
        "tool_use_id TEXT, tool_name TEXT, started_at TEXT, completed_at TEXT);"
    )
    conn.execute(
        "INSERT INTO session_tool_calls VALUES (1,?,'call','Shell',?,NULL)",
        (NATIVE_WAKE_SESSION_ID, MESSAGE_NOW.isoformat()),
    )
    conn.commit()
    yield conn, idle_supported
    conn.close()


def _queue(conn):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Continue the current work.",
        now=SWEEP - timedelta(seconds=1),
    )["message_id"]


@pytest.mark.parametrize("wake_connection", SURFACES, indirect=True)
def test_a_stale_open_call_defers_without_recording_an_unsupported_wake(
    wake_connection,
):
    conn, _ = wake_connection
    message_id = _queue(conn)
    row = dict(
        conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=?",
            (NATIVE_WAKE_SESSION_ID,),
        ).fetchone()
    )
    assert activity_liveness(row, now=SWEEP) == "stale"
    assert wake_eligible_recipients(conn, now=SWEEP) == []
    receipt = conn.execute(
        "SELECT state,wake_attempt_count,last_wake_at FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert tuple(receipt) == ("pending", 0, None)
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 0
    )


@pytest.mark.parametrize("wake_connection", SURFACES, indirect=True)
def test_a_completed_call_keeps_the_manifest_selected_idle_route(wake_connection):
    conn, idle_supported = wake_connection
    _queue(conn)
    conn.execute(
        "UPDATE session_tool_calls SET completed_at=?", (MESSAGE_NOW.isoformat(),)
    )
    conn.commit()
    eligible = wake_eligible_recipients(conn, now=SWEEP)
    assert bool(eligible) == idle_supported
    if eligible:
        assert eligible[0]["wake_mode"] == "idle_timeout"
        assert eligible[0]["liveness"] == "stale"


@pytest.mark.parametrize("wake_connection", SURFACES, indirect=True)
def test_returning_from_a_long_call_delivers_through_its_existing_hook(
    wake_connection, monkeypatch
):
    from yoke_core.domain import session_message_delivery

    conn, _ = wake_connection
    message_id = _queue(conn)
    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: SWEEP)
    conn.execute("UPDATE session_tool_calls SET completed_at=?", (SWEEP.isoformat(),))
    conn.commit()
    lease = lease_for_hook(
        conn, session_id=NATIVE_WAKE_SESSION_ID, hook_event="PostToolUse", limit=10
    )
    assert lease is not None
    assert [message["message_id"] for message in lease["messages"]] == [message_id]
    assert (
        complete_hook_lease(
            conn, lease_id=lease["lease_id"], injected=True, result="injected"
        )
        == 1
    )
    assert wake_eligible_recipients(conn, now=SWEEP) == []


@pytest.mark.parametrize("wake_connection", SURFACES[:3], indirect=True)
@pytest.mark.parametrize("stopped", [False, True])
def test_waiting_or_stopped_sessions_keep_the_supported_resume(
    wake_connection, stopped
):
    conn, _ = wake_connection
    _queue(conn)
    conn.execute(
        "UPDATE session_tool_calls SET completed_at=?", (MESSAGE_NOW.isoformat(),)
    )
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting',ended_at=? WHERE session_id=?",
        (MESSAGE_NOW.isoformat() if stopped else None, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    candidate = wake_eligible_recipients(conn, now=SWEEP)[0]
    assert candidate["wake_mode"] == "waiting"
    assert candidate["liveness"] == ("ended" if stopped else "stale")


@pytest.mark.parametrize("wake_connection", SURFACES[:3], indirect=True)
def test_an_explicit_wake_is_not_held_by_a_stale_open_call(wake_connection):
    conn, _ = wake_connection
    result = request_session_wake(
        conn,
        actor_id=10,
        caller_session_id=None,
        session_id=NATIVE_WAKE_SESSION_ID,
        public_ref=None,
        prompt=None,
        now=SWEEP,
    )
    candidate = wake_eligible_recipients(conn, now=SWEEP)[0]
    assert candidate["message_id"] == result["message_id"]
    assert candidate["wake_mode"] == "waiting"


@pytest.mark.parametrize("wake_connection", SURFACES[:3], indirect=True)
def test_a_verified_exit_retires_a_stale_orphaned_call(wake_connection):
    conn, _ = wake_connection
    _queue(conn)
    record_process_gone(conn, when=MESSAGE_NOW + timedelta(minutes=1))
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id=?",
        (NATIVE_WAKE_SESSION_ID,),
    )
    conn.commit()
    candidate = wake_eligible_recipients(conn, now=SWEEP)[0]
    assert candidate["wake_mode"] == "waiting"


@pytest.mark.parametrize("wake_connection", SURFACES[:3], indirect=True)
def test_an_ended_waiter_is_not_held_by_an_orphaned_call(wake_connection):
    conn, _ = wake_connection
    _queue(conn)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting',ended_at=? WHERE session_id=?",
        (MESSAGE_NOW.isoformat(), NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    candidate = wake_eligible_recipients(conn, now=SWEEP)[0]
    assert candidate["liveness"] == "ended"
    assert candidate["wake_mode"] == "waiting"
