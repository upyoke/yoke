"""Boot-convergence coverage for recorded item-worktree commit identity."""

from __future__ import annotations

import sqlite3

from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema


def _legacy_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE items (id INTEGER PRIMARY KEY);
        INSERT INTO items (id) VALUES (7);
        CREATE TABLE item_worktrees (
          id INTEGER PRIMARY KEY,
          item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
          branch TEXT NOT NULL,
          path TEXT,
          lane_role TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          released_at TEXT
        );
        INSERT INTO item_worktrees (
          id, item_id, branch, path, lane_role, state, created_at, updated_at
        ) VALUES (
          3, 7, 'feature/recorded-head', '/tmp/recorded-head',
          'implementation', 'active', 'now', 'now'
        );
        """
    )
    return conn


def test_boot_converges_commit_identity_on_an_existing_lane_table() -> None:
    conn = _legacy_connection()

    ensure_item_worktree_schema(conn)
    ensure_item_worktree_schema(conn)

    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(item_worktrees)")
    }
    lane = conn.execute(
        "SELECT branch, state, commit_sha FROM item_worktrees WHERE id = 3"
    ).fetchone()

    assert "commit_sha" in columns
    assert dict(lane) == {
        "branch": "feature/recorded-head",
        "state": "active",
        "commit_sha": None,
    }
