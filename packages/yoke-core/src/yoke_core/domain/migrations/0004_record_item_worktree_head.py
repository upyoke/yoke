"""Record the committed head owned by each item worktree lane."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _column_exists, _table_exists


def apply(conn: Any) -> None:
    """Add the nullable head identity without rewriting existing lanes."""
    if _table_exists(conn, "item_worktrees") and not _column_exists(
        conn, "item_worktrees", "commit_sha"
    ):
        conn.execute("ALTER TABLE item_worktrees ADD COLUMN commit_sha TEXT")


def invariants(conn: Any) -> None:
    """Require every current universe to expose the lane-head column."""
    if not _column_exists(conn, "item_worktrees", "commit_sha"):
        raise AssertionError("item_worktrees.commit_sha is missing")
