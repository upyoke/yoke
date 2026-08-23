"""Order and activity coverage for durable native-turn posture."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_turn_posture import (
    accepted_hook_posture,
    stamp_turn_posture,
)


BASE = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE harness_sessions ("
        "session_id TEXT PRIMARY KEY,"
        "turn_posture TEXT NOT NULL DEFAULT 'unknown',"
        "turn_posture_at TEXT,ended_at TEXT,last_chain_step INTEGER)"
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,ended_at,last_chain_step) VALUES ('s1','already-ended',9)"
    )
    return conn


@pytest.mark.parametrize(
    ("event_name", "outcome", "timed_out", "failed", "expected"),
    [
        ("Stop", "allow", False, False, "waiting"),
        ("SessionEnd", "allow", False, False, "waiting"),
        ("UserPromptSubmit", "allow", False, False, "running"),
        ("Stop", "deny", False, False, None),
        ("Stop", "allow", True, False, None),
        ("Stop", "allow", False, True, None),
    ],
)
def test_only_accepted_aggregate_hooks_map_to_posture(
    event_name, outcome, timed_out, failed, expected
) -> None:
    assert (
        accepted_hook_posture(
            event_name,
            final_outcome=outcome,
            timed_out=timed_out,
            failed=failed,
        )
        == expected
    )


def test_delayed_stop_cannot_overwrite_new_prompt_and_running_wins_ties() -> None:
    conn = _connection()
    assert stamp_turn_posture(
        conn,
        session_id="s1",
        posture="running",
        observed_at=BASE + timedelta(seconds=2),
    )
    assert not stamp_turn_posture(
        conn, session_id="s1", posture="waiting", observed_at=BASE
    )
    assert not stamp_turn_posture(
        conn,
        session_id="s1",
        posture="waiting",
        observed_at=BASE + timedelta(seconds=2),
    )
    row = conn.execute(
        "SELECT turn_posture,turn_posture_at,ended_at,last_chain_step "
        "FROM harness_sessions"
    ).fetchone()
    assert tuple(row) == (
        "running",
        "2026-08-23T12:00:02.000000Z",
        "already-ended",
        9,
    )


def test_newer_accepted_stop_moves_running_session_to_waiting() -> None:
    conn = _connection()
    stamp_turn_posture(conn, session_id="s1", posture="running", observed_at=BASE)
    assert stamp_turn_posture(
        conn,
        session_id="s1",
        posture="waiting",
        observed_at=BASE + timedelta(seconds=1),
    )
    assert (
        conn.execute("SELECT turn_posture FROM harness_sessions").fetchone()[0]
        == "waiting"
    )


def test_tool_activity_marks_running_without_claim_or_chain_dependencies() -> None:
    conn = _connection()
    apply_envelope_state(
        conn,
        {
            "event_name": "HarnessToolCallStarted",
            "session_id": "s1",
            "event_time": "2026-08-23T12:00:03.000Z",
            "tool_use_id": "tool-1",
            "tool_name": "Bash",
        },
    )
    row = conn.execute(
        "SELECT turn_posture,turn_posture_at FROM harness_sessions"
    ).fetchone()
    assert tuple(row) == ("running", "2026-08-23T12:00:03.000000Z")


def test_invalid_posture_is_rejected_before_storage() -> None:
    with pytest.raises(ValueError, match="invalid turn posture"):
        stamp_turn_posture(
            _connection(), session_id="s1", posture="idle", observed_at=BASE
        )
