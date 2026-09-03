"""Schema for workflow-neutral item worktree lanes."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)

#: The column the epic lane foreign keys reference. Postgres accepts a foreign
#: key only when the referenced column is covered by a non-partial unique
#: index, so the repair and the refusal below both talk about this one key.
LANE_KEY_COLUMN = "id"
LANE_PRIMARY_KEY_CONSTRAINT = "item_worktrees_pkey"
LANE_KEY_UNIQUE_INDEX = "idx_item_worktrees_id_unique"
EPIC_LANE_REFERENCE_TABLES = ("epic_tasks", "epic_dispatch_chains")


class ItemWorktreeKeyMissing(RuntimeError):
    """The lane table cannot back the epic foreign keys that reference it."""


ITEM_WORKTREES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS item_worktrees (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  branch TEXT NOT NULL,
  path TEXT,
  commit_sha TEXT,
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


def _reference_constraint_list(tables: Sequence[str] = EPIC_LANE_REFERENCE_TABLES) -> str:
    """Name the epic lane foreign keys a refusal is about."""
    return ", ".join(f"fk_{table}_item_worktree" for table in tables)


def lane_key_is_referenceable(conn: Any) -> bool:
    """Return whether ``item_worktrees.id`` can back a foreign key.

    Asks the catalog the same question Postgres asks when it validates
    ``REFERENCES item_worktrees(id)``: is there a valid, non-partial,
    single-column unique index on exactly that column? A primary key answers
    yes through the index it owns; a partial or expression index does not,
    which is why membership is read from ``pg_index`` rather than from the
    presence of any constraint row.
    """
    row = conn.execute(
        """
        SELECT 1
        FROM pg_catalog.pg_index idx
        WHERE idx.indrelid = to_regclass('item_worktrees')
          AND idx.indisunique
          AND idx.indisvalid
          AND idx.indpred IS NULL
          AND idx.indexprs IS NULL
          AND idx.indkey::text = (
            SELECT att.attnum::text
            FROM pg_catalog.pg_attribute att
            WHERE att.attrelid = to_regclass('item_worktrees')
              AND att.attname = %s
          )
        LIMIT 1
        """,
        (LANE_KEY_COLUMN,),
    ).fetchone()
    return row is not None


def _lane_table_has_primary_key(conn: Any) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_catalog.pg_constraint "
        "WHERE conrelid = to_regclass('item_worktrees') AND contype = 'p'"
    ).fetchone()
    return row is not None


def ensure_item_worktree_key(conn: Any) -> None:
    """Give an existing lane table the unique key its references require.

    ``ITEM_WORKTREES_TABLE_SQL`` declares the key, so a table this code
    created already carries it. A table that reached this database by some
    other path — an older shape, a restore, a hand-built validation
    database — may not, and the foreign keys added next would then fail with
    a bare ``there is no unique constraint matching given keys`` from the
    driver, naming neither the table nor what to do about it. Adding the key
    is a creation step: it removes nothing and it is safe to repeat.
    """
    if not db_backend.connection_is_postgres(conn):
        return
    if not _table_exists(conn, "item_worktrees"):
        return
    if lane_key_is_referenceable(conn):
        return
    statement = (
        f"CREATE UNIQUE INDEX {LANE_KEY_UNIQUE_INDEX} "
        f"ON item_worktrees ({LANE_KEY_COLUMN})"
        if _lane_table_has_primary_key(conn)
        else f"ALTER TABLE item_worktrees ADD CONSTRAINT "
        f"{LANE_PRIMARY_KEY_CONSTRAINT} PRIMARY KEY ({LANE_KEY_COLUMN})"
    )
    try:
        conn.execute(statement)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — re-raised as a named refusal
        conn.rollback()
        raise ItemWorktreeKeyMissing(
            f"item_worktrees.{LANE_KEY_COLUMN} carries no unique key, so the "
            f"epic lane foreign keys ({_reference_constraint_list()}) cannot "
            "reference it, and the key could not be added. Statement: "
            f"{statement}. The database refused it: {exc}. Recovery: resolve "
            f"the duplicate or NULL item_worktrees.{LANE_KEY_COLUMN} values "
            "the refusal names, then converge this database again."
        ) from exc


def ensure_item_worktree_schema(conn: Any) -> None:
    """Create the additive universal lane table and ownership indexes."""
    execute_schema_script(conn, ITEM_WORKTREES_TABLE_SQL)
    _add_column_if_not_exists(conn, "item_worktrees", "commit_sha", "TEXT")
    execute_schema_script(conn, ITEM_WORKTREES_INDEX_SQL)
    conn.commit()
    ensure_item_worktree_key(conn)


def ensure_epic_item_worktree_references(conn: Any) -> None:
    """Attach nullable epic lane references once both table families exist."""
    if not db_backend.connection_is_postgres(conn):
        return
    tables = [
        table
        for table in EPIC_LANE_REFERENCE_TABLES
        if _table_exists(conn, table) and _column_exists(conn, table, "item_worktree_id")
    ]
    if not tables:
        return
    if not lane_key_is_referenceable(conn):
        raise ItemWorktreeKeyMissing(
            f"item_worktrees.{LANE_KEY_COLUMN} carries no unique key, so "
            f"{_reference_constraint_list(tables)} cannot be created against "
            "it. Every lane reference needs a valid, non-partial, "
            f"single-column unique index on item_worktrees.{LANE_KEY_COLUMN}. "
            "Recovery: run yoke_core.domain.item_worktree_schema."
            "ensure_item_worktree_key against this database, which adds the "
            "key, and read its refusal if the key cannot be added."
        )
    for table in tables:
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
    "EPIC_LANE_REFERENCE_TABLES",
    "ITEM_WORKTREES_INDEX_SQL",
    "ITEM_WORKTREES_TABLE_SQL",
    "ItemWorktreeKeyMissing",
    "LANE_KEY_COLUMN",
    "LANE_KEY_UNIQUE_INDEX",
    "LANE_PRIMARY_KEY_CONSTRAINT",
    "ensure_epic_item_worktree_references",
    "ensure_item_worktree_key",
    "ensure_item_worktree_schema",
    "lane_key_is_referenceable",
]
