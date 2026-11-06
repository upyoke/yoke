"""Attempt lookup indexes survive repeated migration and serve query plans."""

import importlib
import sqlite3

from runtime.api.domain.session_message_support_test_support import message_connection

migration = importlib.import_module(
    "yoke_core.domain.migrations.0073_session_message_attempt_indexes"
)


def test_existing_attempts_gain_both_lookup_indexes_without_row_changes():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_message_attempts "
        "(attempt_id TEXT PRIMARY KEY, message_id TEXT, target_session_id TEXT)"
    )
    conn.executemany(
        "INSERT INTO session_message_attempts VALUES(?,?,?)",
        [(str(i), f"message-{i}", f"session-{i}") for i in range(1000)],
    )
    before = conn.execute("SELECT * FROM session_message_attempts").fetchall()
    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)
    assert conn.execute("SELECT * FROM session_message_attempts").fetchall() == before
    for name, column in migration.INDEXES.items():
        plan = conn.execute(
            f"EXPLAIN QUERY PLAN SELECT * FROM session_message_attempts WHERE {column}=?",
            ("message-3" if column == "message_id" else "session-3",),
        ).fetchall()
        assert any(f"USING INDEX {name}" in row[3] for row in plan)
        assert not any("SCAN session_message_attempts" in row[3] for row in plan)


def test_born_universe_declares_the_same_lookup_indexes():
    migration.invariants(message_connection())
