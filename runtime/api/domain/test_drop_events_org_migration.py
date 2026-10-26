"""The governed event column drop retains telemetry and drains old builds."""

import importlib
import sqlite3
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum


def test_drop_is_idempotent_and_requires_a_new_serving_build():
    entry = importlib.import_module("yoke_core.domain.migrations.0091_drop_events_org")
    assert declared_minimum(entry) == NEXT_RELEASE
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, org_id TEXT, envelope TEXT)"
    )
    conn.execute("INSERT INTO events VALUES (1, NULL, '{}')")
    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)
    assert [row[1] for row in conn.execute("PRAGMA table_info(events)")] == [
        "id",
        "envelope",
    ]
    assert conn.execute("SELECT * FROM events").fetchall() == [(1, "{}")]


def test_empty_universe_needs_no_drop():
    entry = importlib.import_module("yoke_core.domain.migrations.0091_drop_events_org")
    conn = sqlite3.connect(":memory:")
    entry.apply(conn)
    entry.invariants(conn)
