"""Additive storage for document-led work-item execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.strategy_execution_events import (
    STRATEGY_EXECUTION_EVENT_ROWS,
)


STRATEGY_EXECUTION_TABLE_SQL = """
ALTER TABLE strategy_docs
  ADD COLUMN IF NOT EXISTS parent_slug TEXT;

ALTER TABLE strategy_doc_revisions
  ADD COLUMN IF NOT EXISTS session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_strategy_docs_parent
  ON strategy_docs(project_id, parent_slug)
  WHERE parent_slug IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_strategy_docs (
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  strategy_doc_slug TEXT NOT NULL,
  linked_by_actor_id INTEGER,
  linked_by_session_id TEXT,
  linked_at TEXT NOT NULL,
  UNIQUE(item_id, project_id, strategy_doc_slug),
  FOREIGN KEY(project_id, strategy_doc_slug)
    REFERENCES strategy_docs(project_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_item_strategy_docs_document
  ON item_strategy_docs(project_id, strategy_doc_slug);

CREATE TABLE IF NOT EXISTS strategy_doc_claims (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  strategy_doc_slug TEXT NOT NULL,
  owning_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  registered_by_actor_id INTEGER,
  registered_by_session_id TEXT,
  registered_at TEXT NOT NULL,
  released_by_actor_id INTEGER,
  released_by_session_id TEXT,
  released_at TEXT,
  release_mode TEXT
    CHECK(release_mode IS NULL OR release_mode IN ('normal','break_glass')),
  release_reason TEXT,
  FOREIGN KEY(project_id, strategy_doc_slug)
    REFERENCES strategy_docs(project_id, slug)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_doc_claims_active_document
  ON strategy_doc_claims(project_id, strategy_doc_slug)
  WHERE released_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_doc_claims_active_item
  ON strategy_doc_claims(owning_item_id)
  WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_strategy_doc_claims_item_history
  ON strategy_doc_claims(owning_item_id, registered_at);
"""


def ensure_strategy_execution_schema(
    conn: Any,
    *,
    commit: bool = True,
) -> None:
    """Create storage, committing unless the caller owns the transaction."""
    execute_schema_script(conn, STRATEGY_EXECUTION_TABLE_SQL)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    for event_name, description in STRATEGY_EXECUTION_EVENT_ROWS:
        conn.execute(
            "INSERT INTO event_registry "
            "(event_name, event_kind, event_type, owner_service, description, "
            "severity_default, status) "
            f"VALUES ({marker}, 'workflow', 'strategy_doc', 'engine', "
            f"{marker}, 'INFO', 'active') "
            "ON CONFLICT(event_name) DO UPDATE SET "
            "event_kind=EXCLUDED.event_kind, event_type=EXCLUDED.event_type, "
            "owner_service=EXCLUDED.owner_service, "
            "description=EXCLUDED.description, status='active'",
            (event_name, description),
        )
    if commit:
        conn.commit()


__all__ = [
    "STRATEGY_EXECUTION_TABLE_SQL",
    "ensure_strategy_execution_schema",
]
