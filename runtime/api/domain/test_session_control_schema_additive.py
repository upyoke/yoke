"""Additive convergence for session-control tables on pre-existing databases.

``CREATE TABLE IF NOT EXISTS`` never alters a table that already exists, so a
column added to a table's create statement after that table first shipped
reaches only databases born afterwards. The schema converge must therefore
also carry an additive ALTER for every such column; these tests pin that
contract for ``session_launch_attempts.batch_id``, which a live fleet was
missing while the running build read it.
"""

from __future__ import annotations

import sqlite3

from yoke_core.domain.session_control_schema import create_session_control_tables


# The table shape as it first shipped, before batch_id existed — the shape a
# database born from an older build still has when the converge runs.
_LAUNCH_ATTEMPTS_BEFORE_BATCH_ID = """
    CREATE TABLE session_launch_attempts (
        attempt_id TEXT PRIMARY KEY,
        launch_id TEXT NOT NULL,
        relay_id TEXT,
        machine_id TEXT NOT NULL,
        lease_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        adapter_revision TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        native_session_id TEXT,
        result_code TEXT,
        evidence TEXT,
        UNIQUE(launch_id, attempt_number)
    )
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_pre_existing_launch_attempts_table_gains_batch_id() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(_LAUNCH_ATTEMPTS_BEFORE_BATCH_ID)
    assert "batch_id" not in _columns(conn, "session_launch_attempts")

    create_session_control_tables(conn)

    assert "batch_id" in _columns(conn, "session_launch_attempts")


def test_converge_is_idempotent_on_an_already_current_table() -> None:
    conn = sqlite3.connect(":memory:")
    create_session_control_tables(conn)
    create_session_control_tables(conn)

    assert "batch_id" in _columns(conn, "session_launch_attempts")


def test_fresh_and_aged_databases_converge_to_the_same_columns() -> None:
    fresh = sqlite3.connect(":memory:")
    create_session_control_tables(fresh)

    aged = sqlite3.connect(":memory:")
    aged.execute(_LAUNCH_ATTEMPTS_BEFORE_BATCH_ID)
    create_session_control_tables(aged)

    assert _columns(fresh, "session_launch_attempts") == _columns(
        aged, "session_launch_attempts"
    )
