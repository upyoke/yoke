"""Boot-convergence coverage for the item-worktree lane table.

Two shapes reach the converge: a lane table that predates ``commit_sha``, and
one carrying no unique key on ``id`` at all — which the epic lane foreign keys
reference, and which a database born outside this code may simply not have.
"""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.item_worktree_schema import (
    EPIC_LANE_REFERENCE_TABLES,
    ItemWorktreeKeyMissing,
    LANE_PRIMARY_KEY_CONSTRAINT,
    ensure_epic_item_worktree_references,
    ensure_item_worktree_key,
    ensure_item_worktree_schema,
    lane_key_is_referenceable,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from runtime.api.fixtures.pg_testdb import test_database


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


def _strip_lane_key(conn) -> None:
    """Leave item_worktrees the way a table born without its key looks."""
    for table in EPIC_LANE_REFERENCE_TABLES:
        conn.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_item_worktree"
        )
    conn.execute(
        f"ALTER TABLE item_worktrees DROP CONSTRAINT {LANE_PRIMARY_KEY_CONSTRAINT}"
    )
    conn.commit()


def _lane_reference_constraints(conn) -> set:
    rows = conn.execute(
        "SELECT conname FROM pg_catalog.pg_constraint "
        "WHERE conname IN ('fk_epic_tasks_item_worktree', "
        "'fk_epic_dispatch_chains_item_worktree')"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_converge_gives_a_key_less_lane_table_the_key_its_references_need() -> None:
    with test_database() as conn:
        _strip_lane_key(conn)
        assert lane_key_is_referenceable(conn) is False

        ensure_item_worktree_schema(conn)
        ensure_epic_item_worktree_references(conn)

        assert lane_key_is_referenceable(conn) is True
        assert _lane_reference_constraints(conn) == {
            "fk_epic_tasks_item_worktree",
            "fk_epic_dispatch_chains_item_worktree",
        }


def test_lane_references_refuse_by_name_when_the_key_is_still_absent() -> None:
    with test_database() as conn:
        _strip_lane_key(conn)

        with pytest.raises(ItemWorktreeKeyMissing) as refusal:
            ensure_epic_item_worktree_references(conn)

        message = str(refusal.value)
        assert "item_worktrees.id" in message
        assert "fk_epic_tasks_item_worktree" in message
        assert "fk_epic_dispatch_chains_item_worktree" in message


def test_a_key_that_cannot_be_added_refuses_with_the_recovery_step() -> None:
    with test_database() as conn:
        _strip_lane_key(conn)
        insert_item(conn, id=91, title="lane owner")
        for branch in ("first", "second"):
            insert_item_worktree(
                conn, id=4242, item_id=91, branch=branch,
                lane_role="worker", state="released",
            )
        conn.commit()

        with pytest.raises(ItemWorktreeKeyMissing) as refusal:
            ensure_item_worktree_key(conn)

        message = str(refusal.value)
        assert "item_worktrees.id" in message
        assert "Recovery:" in message
