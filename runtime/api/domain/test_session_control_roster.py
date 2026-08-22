"""Read-time fleet roster enrichment and capability projection tests."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from runtime.api.test_constants import TEST_ITEM_ID, TEST_ITEM_REF
from yoke_core.domain.session_control_roster import (
    SESSION_CONTROL_ROSTER_FIELDS,
    session_control_roster_result,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            executor_version TEXT,
            machine_id TEXT,
            last_heartbeat TEXT,
            last_tool_call_at TEXT,
            ended_at TEXT
        );
        CREATE TABLE session_relays (
            relay_id TEXT PRIMARY KEY,
            machine_id TEXT,
            connected_until TEXT,
            state TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
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
        """
    )
    return conn


def test_roster_enriches_version_machine_relay_and_messageability() -> None:
    conn = _connection()
    conn.execute(
        "INSERT INTO harness_sessions VALUES (?,?,?,?,?,?)",
        (
            "session-1",
            "26.814.41407",
            "machine-1",
            "2026-08-22T12:00:00Z",
            "2026-08-22T12:00:00Z",
            None,
        ),
    )
    conn.execute(
        "INSERT INTO session_relays VALUES (?,?,?,?)",
        (
            "relay-1",
            "machine-1",
            "2026-08-22T12:05:00Z",
            "active",
        ),
    )
    conn.execute(
        "INSERT INTO item_worktrees VALUES (?,?,?,?,?,?)",
        (
            1,
            TEST_ITEM_ID,
            "/repo/.worktrees/item-42",
            "item-42",
            "active",
            "worker",
        ),
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (?,?,?,?,?,?,?,?)",
        (
            1,
            "session-1",
            "item",
            TEST_ITEM_ID,
            None,
            None,
            "2026-08-22T11:00:00Z",
            None,
        ),
    )
    base = [
        {
            "session_id": "session-1",
            "project": "yoke",
            "claims": [{"target_kind": "item", "target": TEST_ITEM_REF}],
            "current_item": TEST_ITEM_REF,
            "work_role": "implementation",
            "workspace": "/repo",
            "executor": "codex",
            "executor_surface": "codex-desktop",
            "liveness": "active",
            "messageability": {"messageable": False, "reason": "stale-cache"},
        }
    ]

    result = session_control_roster_result(
        base,
        conn=conn,
        now=datetime(2026, 8, 22, 12, 1, tzinfo=timezone.utc),
    )

    assert result["fields"] == list(SESSION_CONTROL_ROSTER_FIELDS)
    row = result["rows"][0]
    assert row["focus"] == TEST_ITEM_REF
    assert row["role"] == "implementation"
    assert row["worktree"] == "/repo/.worktrees/item-42"
    assert row["executor_version"] == "26.814.41407"
    assert row["machine_id"] == "machine-1"
    assert row["relay"] == "connected"
    assert row["messageability"]["messageable"] is True
    assert row["messageability"]["relay_connected"] is True
    assert row["messageability"]["wake_available"] is True


def test_empty_roster_has_the_complete_stable_field_contract() -> None:
    assert session_control_roster_result([]) == {
        "fields": list(SESSION_CONTROL_ROSTER_FIELDS),
        "rows": [],
    }
