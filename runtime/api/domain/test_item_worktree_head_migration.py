"""Additive migration coverage for recorded item-worktree heads."""

from __future__ import annotations

import importlib
import sqlite3


migration = importlib.import_module(
    "yoke_core.domain.migrations.0004_record_item_worktree_head"
)


def _legacy_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE item_worktrees ("
        "id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, branch TEXT NOT NULL)"
    )
    return conn


def test_adds_the_nullable_commit_identity_idempotently() -> None:
    conn = _legacy_connection()

    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(item_worktrees)")
    }
    assert "commit_sha" in columns
