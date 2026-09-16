"""Latest tool-call projections read the newest started row, not MAX(id)."""

from __future__ import annotations

import sqlite3

from yoke_core.domain.session_tool_call_projections import (
    LAST_COMPLETED_TOOL_COLUMN,
    OPEN_TOOL_CALL_COLUMN,
    last_completed_tool_select,
    open_tool_call_select,
)

SESSION = "sess-1"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY);
        CREATE TABLE session_tool_calls (
          id INTEGER PRIMARY KEY,
          session_id TEXT NOT NULL,
          tool_use_id TEXT NOT NULL,
          tool_name TEXT,
          started_at TEXT NOT NULL,
          completed_at TEXT
        );
        CREATE INDEX idx_session_tool_calls_session_started
          ON session_tool_calls(session_id, started_at);
        INSERT INTO harness_sessions VALUES ('sess-1');
        """
    )
    return conn


def _add(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    tool: str,
    started: str,
    completed: str | None,
) -> None:
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(id,session_id,tool_use_id,tool_name,started_at,completed_at) "
        "VALUES (?,?,?,?,?,?)",
        (row_id, SESSION, f"use-{row_id}", tool, started, completed),
    )


def _project(conn: sqlite3.Connection) -> sqlite3.Row:
    sql = (
        "SELECT hs.session_id"
        f"{open_tool_call_select(conn, session_alias='hs')}"
        f"{last_completed_tool_select(conn, session_alias='hs')} "
        "FROM harness_sessions hs"
    )
    return conn.execute(sql).fetchone()


def test_open_call_is_the_newest_started_row_when_still_open() -> None:
    conn = _conn()
    _add(conn, row_id=1, tool="Read", started="t1", completed="t2")
    _add(conn, row_id=2, tool="Monitor", started="t3", completed=None)
    row = _project(conn)
    assert row[OPEN_TOOL_CALL_COLUMN] == "t3"
    assert row[LAST_COMPLETED_TOOL_COLUMN] == "Read"


def test_completed_newest_row_clears_open_call() -> None:
    conn = _conn()
    _add(conn, row_id=1, tool="Read", started="t1", completed="t2")
    _add(conn, row_id=2, tool="Monitor", started="t3", completed="t4")
    row = _project(conn)
    assert row[OPEN_TOOL_CALL_COLUMN] is None
    assert row[LAST_COMPLETED_TOOL_COLUMN] == "Monitor"


def test_older_open_row_does_not_count_after_a_newer_completed_call() -> None:
    conn = _conn()
    _add(conn, row_id=1, tool="Read", started="t1", completed=None)
    _add(conn, row_id=2, tool="Edit", started="t2", completed="t3")
    row = _project(conn)
    assert row[OPEN_TOOL_CALL_COLUMN] is None
    assert row[LAST_COMPLETED_TOOL_COLUMN] == "Edit"


def test_missing_tool_call_table_projects_absence() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO harness_sessions VALUES ('sess-1')")
    sql = (
        "SELECT hs.session_id"
        f"{open_tool_call_select(conn, session_alias='hs')}"
        f"{last_completed_tool_select(conn, session_alias='hs')} "
        "FROM harness_sessions hs"
    )
    row = conn.execute(sql).fetchone()
    assert row[OPEN_TOOL_CALL_COLUMN] is None
    assert row[LAST_COMPLETED_TOOL_COLUMN] is None
