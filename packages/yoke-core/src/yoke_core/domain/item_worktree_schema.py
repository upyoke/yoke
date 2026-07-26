"""Schema for workflow-neutral item worktree lanes."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script

ITEM_WORKTREES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS item_worktrees (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  session_id TEXT,
  branch TEXT NOT NULL,
  path TEXT,
  lane_role TEXT NOT NULL
    CHECK(lane_role IN ('implementation','worker','integration')),
  state TEXT NOT NULL DEFAULT 'active'
    CHECK(state IN ('active','released')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  released_at TEXT
);
"""

ITEM_WORKTREES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_item_worktrees_item_state
  ON item_worktrees(item_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_worktrees_active_item_branch
  ON item_worktrees(item_id, branch)
  WHERE state = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_worktrees_active_path
  ON item_worktrees(path)
  WHERE state = 'active' AND path IS NOT NULL AND path <> '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_worktrees_active_single_lane
  ON item_worktrees(item_id, lane_role)
  WHERE state = 'active'
    AND lane_role IN ('implementation', 'integration');
"""


def ensure_item_worktree_schema(conn: Any) -> None:
    """Create the additive universal lane table and ownership indexes."""
    execute_schema_script(conn, ITEM_WORKTREES_TABLE_SQL)
    execute_schema_script(conn, ITEM_WORKTREES_INDEX_SQL)
    conn.commit()


__all__ = [
    "ITEM_WORKTREES_INDEX_SQL",
    "ITEM_WORKTREES_TABLE_SQL",
    "ensure_item_worktree_schema",
]
