"""Latest wake-attempt resume state includes attempts with no recipient."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_contracts.session_control.wake_delivery import WAKE_DELIVERED_RESULT
from yoke_core.domain.session_control_roster import session_control_roster_result

NOW = datetime(2026, 8, 22, 12, 1, tzinfo=timezone.utc)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            project_id INTEGER,
            executor_surface TEXT,
            executor_version TEXT,
            machine_id TEXT,
            last_heartbeat TEXT,
            last_tool_call_at TEXT,
            ended_at TEXT,
            terminated_at TEXT,
            turn_posture TEXT,
            turn_posture_at TEXT,
            offer_envelope TEXT,
            model TEXT,
            requested_model TEXT
        );
        CREATE TABLE session_relays (
            relay_id TEXT PRIMARY KEY,
            machine_id TEXT,
            hostname TEXT,
            last_seen_at TEXT,
            connected_until TEXT,
            state TEXT,
            surface_versions TEXT,
            project_checkouts TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            item_worktree_id INTEGER
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            path TEXT,
            branch TEXT,
            state TEXT,
            lane_role TEXT
        );
        CREATE TABLE session_message_recipients (
            message_id TEXT,
            session_id TEXT,
            state TEXT,
            created_at TEXT,
            wake_attempt_count INTEGER
        );
        CREATE TABLE session_message_attempts (
            attempt_id TEXT PRIMARY KEY,
            message_id TEXT,
            target_session_id TEXT,
            result_code TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        INSERT INTO harness_sessions VALUES (
            'session-1',10,'claude-desktop','1.0','machine-1',
            '2026-08-22T12:00:00Z','2026-08-22T12:00:00Z',
            NULL,NULL,'running','2026-08-22T12:00:00Z',NULL,NULL,NULL
        );
        """
    )
    return conn


def _row() -> dict[str, object]:
    return {
        "session_id": "session-1",
        "project": "yoke",
        "claims": [],
        "executor": "claude",
        "executor_surface": "claude-desktop",
        "liveness": "active",
    }


def _attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    message_id: str,
    result_code: str,
    started_at: str,
    with_recipient: bool = True,
) -> None:
    if with_recipient:
        conn.execute(
            "INSERT INTO session_message_recipients VALUES (?,?,?,?,?)",
            (message_id, "session-1", "injected", started_at, 0),
        )
    conn.execute(
        "INSERT INTO session_message_attempts VALUES (?,?,?,?,?,?)",
        (attempt_id, message_id, "session-1", result_code, started_at, None),
    )


def _resume(conn: sqlite3.Connection) -> str:
    return session_control_roster_result(
        [_row()],
        conn=conn,
        now=NOW,
    )["rows"][0]["resume_state"]


def test_resume_state_uses_the_newest_attempt() -> None:
    conn = _conn()
    _attempt(
        conn,
        attempt_id="old",
        message_id="msg-old",
        result_code=RESUMED_RUNNING_RESULT,
        started_at="2026-08-22T11:00:00Z",
    )
    _attempt(
        conn,
        attempt_id="new",
        message_id="msg-new",
        result_code=WAKE_DELIVERED_RESULT,
        started_at="2026-08-22T12:00:10Z",
    )
    assert _resume(conn) == "wake-delivered"


def test_orphan_attempt_without_recipient_still_counts() -> None:
    conn = _conn()
    _attempt(
        conn,
        attempt_id="old",
        message_id="msg-old",
        result_code=RESUMED_RUNNING_RESULT,
        started_at="2026-08-22T11:00:00Z",
    )
    _attempt(
        conn,
        attempt_id="orphan",
        message_id="msg-orphan",
        result_code=WAKE_DELIVERED_RESULT,
        started_at="2026-08-22T12:00:10Z",
        with_recipient=False,
    )
    assert _resume(conn) == "wake-delivered"


def test_same_started_at_uses_higher_attempt_id() -> None:
    conn = _conn()
    stamp = "2026-08-22T12:00:10Z"
    _attempt(
        conn,
        attempt_id="aaa",
        message_id="msg-a",
        result_code=RESUMED_RUNNING_RESULT,
        started_at=stamp,
    )
    _attempt(
        conn,
        attempt_id="zzz",
        message_id="msg-z",
        result_code=WAKE_DELIVERED_RESULT,
        started_at=stamp,
    )
    assert _resume(conn) == "wake-delivered"
