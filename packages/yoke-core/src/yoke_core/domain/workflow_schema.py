"""Schema convergence for immutable workflow definitions and item pins."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.schema_init_apply import execute_schema_script

WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER = "workflow_versions_immutable"

WORKFLOWS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('built_in','pack','project')),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
  current_version_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

WORKFLOW_VERSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workflow_versions (
  id INTEGER PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(id),
  version INTEGER NOT NULL CHECK(version > 0),
  definition_schema_version INTEGER NOT NULL CHECK(definition_schema_version > 0),
  definition_json TEXT NOT NULL,
  definition_digest TEXT NOT NULL,
  published_at TEXT NOT NULL,
  published_by_actor_id INTEGER,
  immutable_at TEXT NOT NULL,
  UNIQUE(workflow_id, version),
  UNIQUE(workflow_id, definition_digest)
);
"""

WORKFLOW_VERSION_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_workflow_versions_workflow
  ON workflow_versions(workflow_id, version);
"""

WORKFLOW_TABLES_SQL = "\n".join(
    (
        WORKFLOWS_TABLE_SQL,
        WORKFLOW_VERSIONS_TABLE_SQL,
        WORKFLOW_VERSION_INDEX_SQL,
    )
)

_SQLITE_IMMUTABLE_TRIGGERS = (
    f"""
    CREATE TRIGGER IF NOT EXISTS {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_update
    BEFORE UPDATE ON workflow_versions
    BEGIN
      SELECT RAISE(
        ABORT,
        'published workflow versions are immutable; publish a new version'
      );
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_delete
    BEFORE DELETE ON workflow_versions
    BEGIN
      SELECT RAISE(
        ABORT,
        'published workflow versions are immutable; disable the workflow'
      );
    END
    """,
)

_POSTGRES_IMMUTABLE_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_fn()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION
      'published workflow versions are immutable; disable the workflow';
  END IF;
  RAISE EXCEPTION
    'published workflow versions are immutable; publish a new version';
END;
$$;
"""

_POSTGRES_IMMUTABLE_TRIGGER = f"""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgname = '{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}'
      AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}
    BEFORE UPDATE OR DELETE ON workflow_versions
    FOR EACH ROW
    EXECUTE FUNCTION {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_fn();
  END IF;
END
$$;
"""


def _ensure_immutable_version_triggers(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        function_exists = conn.execute(
            "SELECT 1 FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' "
            "AND p.proname = %s",
            (f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_fn",),
        ).fetchone()
        if function_exists is None:
            conn.execute(_POSTGRES_IMMUTABLE_FUNCTION)
        trigger_exists = conn.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname = %s AND NOT tgisinternal",
            (WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,),
        ).fetchone()
        if trigger_exists is None:
            conn.execute(_POSTGRES_IMMUTABLE_TRIGGER)
        return
    for statement in _SQLITE_IMMUTABLE_TRIGGERS:
        conn.execute(statement)


def ensure_workflow_registry_tables(conn: Any) -> None:
    """Create only missing registry objects, preserving managed ownership."""
    if not _table_exists(conn, "workflows"):
        execute_schema_script(conn, WORKFLOWS_TABLE_SQL)
    if not _table_exists(conn, "workflow_versions"):
        execute_schema_script(conn, WORKFLOW_VERSIONS_TABLE_SQL)
    if not _index_exists(
        conn,
        "idx_workflow_versions_workflow",
        "workflow_versions",
    ):
        execute_schema_script(conn, WORKFLOW_VERSION_INDEX_SQL)


def ensure_workflow_schema(conn: Any) -> None:
    """Converge the additive registry schema and item pin columns."""
    ensure_workflow_registry_tables(conn)
    _add_column_if_not_exists(
        conn,
        "items",
        "workflow_id",
        "TEXT REFERENCES workflows(id)",
    )
    _add_column_if_not_exists(
        conn,
        "items",
        "workflow_version_id",
        "INTEGER REFERENCES workflow_versions(id)",
    )
    _add_column_if_not_exists(
        conn,
        "items",
        "workflow_posture",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_items_workflow "
        "ON items(workflow_id, workflow_version_id)"
    )
    _ensure_immutable_version_triggers(conn)
    conn.commit()


__all__ = [
    "WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER",
    "WORKFLOW_TABLES_SQL",
    "ensure_workflow_registry_tables",
    "ensure_workflow_schema",
]
