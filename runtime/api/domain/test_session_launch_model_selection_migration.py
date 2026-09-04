"""Ordered migration coverage for session launch model-selection requests."""

from __future__ import annotations

import importlib
import sqlite3

from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum


ENTRY_NAME = "0037_session_launch_model_selection"


def _entry():
    return importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(_entry()) == NEXT_RELEASE


def test_apply_is_idempotent_and_preserves_existing_launches() -> None:
    entry = _entry()
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_launches ("
        "launch_id TEXT PRIMARY KEY, state TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO session_launches VALUES ('launch-1', 'launching')")

    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    columns = {
        row[1]: row[2] for row in conn.execute("PRAGMA table_info(session_launches)")
    }
    assert columns["requested_reasoning_effort"] == "TEXT"
    assert columns["requested_context_window_tokens"] == "INTEGER"
    assert conn.execute(
        "SELECT launch_id, state, requested_reasoning_effort, "
        "requested_context_window_tokens FROM session_launches"
    ).fetchall() == [("launch-1", "launching", None, None)]


def test_apply_is_a_noop_when_launch_table_is_absent() -> None:
    conn = sqlite3.connect(":memory:")

    _entry().apply(conn)
    _entry().invariants(conn)
