"""Schema convergence for immutable workflow definitions and item pins."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script

WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER = "workflow_versions_immutable"

WORKFLOW_TABLES_SQL = """
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
CREATE INDEX IF NOT EXISTS idx_workflow_versions_workflow
  ON workflow_versions(workflow_id, version);
"""

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
        conn.execute(_POSTGRES_IMMUTABLE_FUNCTION)
        conn.execute(_POSTGRES_IMMUTABLE_TRIGGER)
        return
    for statement in _SQLITE_IMMUTABLE_TRIGGERS:
        conn.execute(statement)


def ensure_workflow_schema(conn: Any) -> None:
    """Converge the additive registry schema and item pin columns."""
    execute_schema_script(conn, WORKFLOW_TABLES_SQL)
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
    "ensure_workflow_schema",
]
