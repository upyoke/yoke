"""Open-attempt and latest-tool-call indexes apply idempotently and serve plans."""

import importlib
import sqlite3

from runtime.api.domain.session_message_support_test_support import message_connection
from yoke_core.domain.schema_init_tables_sessions import create_session_tables

migration = importlib.import_module(
    "yoke_core.domain.migrations.0076_open_attempt_and_latest_tool_call_indexes"
)

PLANS = {
    "idx_session_message_attempts_open_lease": (
        "SELECT 1 FROM session_message_attempts "
        "WHERE lease_id=? AND completed_at IS NULL LIMIT 1",
        ("lease-3",),
    ),
    "idx_session_message_attempts_open_started": (
        "SELECT attempt_id FROM session_message_attempts "
        "WHERE completed_at IS NULL ORDER BY started_at,attempt_id",
        (),
    ),
    "idx_session_tool_calls_session_id_id": (
        "SELECT MAX(id) FROM session_tool_calls WHERE session_id=?",
        ("session-3",),
    ),
}


def test_indexes_apply_idempotently_serve_plans_and_match_born_schema():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_message_attempts (attempt_id TEXT PRIMARY KEY, "
        "lease_id TEXT, started_at TEXT, completed_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE session_tool_calls (id INTEGER PRIMARY KEY, session_id TEXT, "
        "tool_use_id TEXT)"
    )
    conn.executemany(
        "INSERT INTO session_message_attempts VALUES(?,?,?,?)",
        [
            (str(i), f"lease-{i}", f"2026-10-14T{i % 24:02}", None if i % 50 else "x")
            for i in range(1000)
        ],
    )
    conn.executemany(
        "INSERT INTO session_tool_calls VALUES(?,?,?)",
        [(i, f"session-{i % 40}", f"use-{i}") for i in range(1000)],
    )
    before = [
        conn.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("session_message_attempts", "session_tool_calls")
    ]
    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)
    assert before == [
        conn.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("session_message_attempts", "session_tool_calls")
    ]
    for name, (sql, params) in PLANS.items():
        plan = [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params)]
        assert any(name in step for step in plan), (name, plan)

    born = message_connection()
    create_session_tables(born)
    migration.invariants(born)
