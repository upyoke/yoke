"""Ordered migration coverage for presentation and launch names."""

from __future__ import annotations

import importlib
import sqlite3


def test_migration_is_idempotent_and_declares_all_columns():
    migration = importlib.import_module(
        "yoke_core.domain.migrations.0023_session_presentation_and_launch_name"
    )
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE session_launches (launch_id TEXT PRIMARY KEY)")

    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)

    session_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(harness_sessions)")
    }
    assert {
        "presentation_surface",
        "presentation_state",
        "presentation_mode",
        "presentation_source",
        "presentation_observed_at",
    } <= session_columns
    launch_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(session_launches)")
    }
    assert "session_name" in launch_columns
