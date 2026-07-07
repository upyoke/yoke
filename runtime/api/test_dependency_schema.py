"""Shared schema helpers for dependency-related API tests.

This module centralizes the canonical current ``item_dependencies`` DDL and a
test-friendly ``items`` schema used across Python unit tests.

The ``items`` table intentionally mirrors the current column surface without
enforcing lifecycle CHECK constraints. A few API tests seed legacy or invalid
statuses on purpose to verify startup guards, and those tests should not need
their own private copy of the table definition just to bypass constraints.
"""

from __future__ import annotations

from typing import Any


PROJECTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  emoji TEXT DEFAULT '',
  default_branch TEXT DEFAULT 'main',
  github_repo TEXT,
  public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
  github_sync_mode TEXT,
  created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
);
INSERT INTO projects (id, slug, name, public_item_prefix, created_at)
VALUES
  (1, 'yoke', 'Yoke', 'YOK', '2026-01-01T00:00:00Z'),
  (2, 'buzz', 'Buzz', 'BUZ', '2026-01-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
"""


ITEMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'issue',
  status TEXT NOT NULL DEFAULT 'idea',
  priority TEXT NOT NULL DEFAULT 'medium',
  flow TEXT DEFAULT 'accelerated',
  rework_count INTEGER DEFAULT 0,
  frozen INTEGER DEFAULT 0,
  blocked INTEGER DEFAULT 0,
  blocked_reason TEXT,
  github_issue TEXT,
  deployed_to TEXT,
  worktree TEXT,
  merged_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '2',
  owner TEXT DEFAULT '',
  project_id INTEGER NOT NULL DEFAULT 1,
  project_sequence INTEGER,
  spec TEXT,
  spec_updated_at TEXT,
  spec_updated_by TEXT,
  deployment_flow TEXT,
  deploy_stage TEXT
);
"""


ITEM_DEPENDENCIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS item_dependencies (
  id INTEGER PRIMARY KEY,
  dependent_item TEXT NOT NULL,
  blocking_item TEXT NOT NULL,
  gate_point TEXT NOT NULL DEFAULT 'activation',
  satisfaction TEXT NOT NULL DEFAULT 'status:done',
  source TEXT NOT NULL,
  session_id INTEGER,
  rationale TEXT NOT NULL DEFAULT '',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(dependent_item, blocking_item, gate_point)
);
CREATE INDEX IF NOT EXISTS idx_id_dependent ON item_dependencies(dependent_item);
CREATE INDEX IF NOT EXISTS idx_id_blocking ON item_dependencies(blocking_item);
"""


CLAIM_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS harness_sessions (
  session_id TEXT PRIMARY KEY,
  executor TEXT NOT NULL DEFAULT 'codex',
  project_id INTEGER NOT NULL DEFAULT 1,
  last_heartbeat TEXT,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS work_claims (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  target_kind TEXT NOT NULL DEFAULT 'item',
  item_id INTEGER,
  claimed_at TEXT NOT NULL,
  last_heartbeat TEXT,
  released_at TEXT
);
"""


def create_dependency_test_db() -> Any:
    """Return a disposable Postgres DB with shared dependency tables."""
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_database_on_close,
    )
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    db_name = create_test_database()
    conn = connect_test_database(db_name)
    apply_fixture_ddl(
        conn,
        PROJECTS_SCHEMA + ITEMS_SCHEMA + ITEM_DEPENDENCIES_SCHEMA + CLAIM_STATE_SCHEMA,
    )
    return drop_database_on_close(conn, db_name)
