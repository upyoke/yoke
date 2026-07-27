"""Schema for workflow-neutral item worktree lanes."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists

ITEM_WORKTREES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS item_worktrees (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
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


def ensure_epic_item_worktree_references(conn: Any) -> None:
    """Attach nullable epic lane references once both table families exist."""
    if not db_backend.connection_is_postgres(conn):
        return
    for table in ("epic_tasks", "epic_dispatch_chains"):
        if not _table_exists(conn, table) or not _column_exists(conn, table, "item_worktree_id"):
            continue
        constraint = f"fk_{table}_item_worktree"
        conn.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = '" + constraint + "') THEN ALTER TABLE " + table
            + " ADD CONSTRAINT " + constraint
            + " FOREIGN KEY (item_worktree_id) REFERENCES item_worktrees(id) "
            "ON DELETE SET NULL; END IF; END $$;"
        )
    conn.commit()


__all__ = [
    "ITEM_WORKTREES_INDEX_SQL",
    "ITEM_WORKTREES_TABLE_SQL",
    "ensure_item_worktree_schema",
    "ensure_epic_item_worktree_references",
]
