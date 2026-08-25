"""Storage for document-led work-item execution and document locks.

``strategy_doc_claims`` carries typed ownership: ``owner_kind`` plus the
one matching owner column. An ``item``-owned row is a Blitz holding the
document it executes; a ``session``-owned row is a coordinator holding
the document directly, with no work item. The partial unique index on
``(project_id, strategy_doc_slug)`` makes the two kinds mutually
exclusive on one document. ``registered_by_*`` stays provenance, so an
item-owned claim survives the session that registered it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.strategy_execution_events import (
    STRATEGY_EXECUTION_EVENT_ROWS,
)


STRATEGY_EXECUTION_TABLE_SQL = """
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
  owner_kind TEXT NOT NULL DEFAULT 'item'
    CHECK(owner_kind IN ('item','session')),
  owner_item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
  owner_session_id TEXT REFERENCES harness_sessions(session_id),
  CONSTRAINT strategy_doc_claims_owner_shape_check CHECK (
    (owner_kind = 'item'
       AND owner_item_id IS NOT NULL AND owner_session_id IS NULL)
    OR (owner_kind = 'session'
       AND owner_session_id IS NOT NULL AND owner_item_id IS NULL)
  ),
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

CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_doc_claims_active_owner_item
  ON strategy_doc_claims(owner_item_id)
  WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_strategy_doc_claims_item_history
  ON strategy_doc_claims(owner_item_id, registered_at);

CREATE INDEX IF NOT EXISTS idx_strategy_doc_claims_owner_session
  ON strategy_doc_claims(owner_session_id)
  WHERE released_at IS NULL;
"""


#: Typed-owner columns a database created before the rename still needs.
#: The ordered migration history performs the backfill and retires the
#: item-only column; adding them here keeps the converge self-sufficient
#: when the table already exists.
TYPED_OWNER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("owner_kind", "TEXT NOT NULL DEFAULT 'item'"),
    ("owner_item_id", "INTEGER DEFAULT NULL"),
    ("owner_session_id", "TEXT DEFAULT NULL"),
)


def ensure_strategy_execution_schema(
    conn: Any,
    *,
    commit: bool = True,
) -> None:
    """Create storage, committing unless the caller owns the transaction."""
    _add_column_if_not_exists(conn, "strategy_docs", "parent_slug", "TEXT")
    _add_column_if_not_exists(conn, "strategy_doc_revisions", "session_id", "TEXT")
    execute_schema_script(conn, STRATEGY_EXECUTION_TABLE_SQL)
    for column, ddl in TYPED_OWNER_COLUMNS:
        _add_column_if_not_exists(conn, "strategy_doc_claims", column, ddl)
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
    "TYPED_OWNER_COLUMNS",
    "ensure_strategy_execution_schema",
]
