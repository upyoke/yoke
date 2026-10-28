"""The governed drift-column drop keeps session rows and drains old builds."""

import importlib
import sqlite3

from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.schema_expected_catalog import parse_expected_schema

ENTRY = "yoke_core.domain.migrations.0093_drop_harness_session_drift_columns"


def test_drop_is_idempotent_and_requires_a_new_serving_build():
    entry = importlib.import_module(ENTRY)
    assert declared_minimum(entry) == NEXT_RELEASE
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
        "last_seen_main_sha TEXT, last_drift_check_at TEXT, executor TEXT)"
    )
    conn.execute("INSERT INTO harness_sessions VALUES ('s1', 'abc', NULL, 'codex')")
    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(harness_sessions)")]
    assert columns == ["session_id", "executor"]
    assert conn.execute("SELECT * FROM harness_sessions").fetchall() == [("s1", "codex")]


def test_empty_universe_needs_no_drop():
    entry = importlib.import_module(ENTRY)
    conn = sqlite3.connect(":memory:")
    entry.apply(conn)
    entry.invariants(conn)


def test_the_expected_session_schema_has_no_drift_columns():
    declared = set(parse_expected_schema()["harness_sessions"])
    assert "session_id" in declared
    assert not declared & {"last_seen_main_sha", "last_drift_check_at"}
