"""Shared fixtures for item-worktree migration tests."""

from __future__ import annotations

from typing import Any


def add_legacy_epic_lane_columns(conn: Any) -> None:
    """Model an existing database that predates universal lane references."""
    for table, column in (
        ("items", "worktree"),
        ("epic_tasks", "worktree"),
        ("epic_tasks", "branch"),
        ("epic_tasks", "worktree_path"),
        ("epic_dispatch_chains", "worktree"),
        ("epic_dispatch_chains", "worktree_path"),
    ):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
    conn.commit()


__all__ = ["add_legacy_epic_lane_columns"]
