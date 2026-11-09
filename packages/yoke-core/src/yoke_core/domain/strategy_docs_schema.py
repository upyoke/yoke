"""Storage shape for the strategy-doc authority: doc rows + revision chain.

Declares the ``strategy_docs`` table and its append-only
``strategy_doc_revisions`` history. Revision writes live in
:mod:`yoke_core.domain.strategy_doc_revisions`.

Revision doctrine: every content write (create, replace, ingest)
snapshots the NEW content in the same transaction as the doc-row write,
so the per-doc revision chain reconstructs every state the authority
has held and a bad edit is always recoverable from the prior row.
Rows are immutable — no update or delete surface exists. Two writes
deliberately record nothing: archive/unarchive flips ``archived_at``
without touching content, and cold-start default seeding mints
deterministic placeholder text (backend-aware, including sqlite
install fixtures that carry no revisions table); a seeded doc's chain
starts at its first real edit.
"""

from __future__ import annotations

STRATEGY_DOCS_TABLE = "strategy_docs"
STRATEGY_DOC_REVISIONS_TABLE = "strategy_doc_revisions"

# No FK to actors: validation DBs may carry no actors rows; provenance
# only, never joined for authority. The projects FK is real authority —
# every corpus belongs to exactly one project.
STRATEGY_DOCS_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {STRATEGY_DOCS_TABLE} (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  slug TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL,
  updated_by_actor_id BIGINT,
  -- archived_at: nullable ISO timestamp. NULL = active (renders to
  -- .yoke/strategy/<slug>.md); a timestamp = archived (renders to
  -- .yoke/strategy/archive/<slug>.md). Flipped by strategy.doc.archive /
  -- strategy.doc.unarchive; the doc stays a full, editable corpus row.
  archived_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_docs_project_id_slug
  ON {STRATEGY_DOCS_TABLE}(project_id, slug)
"""

# Doc identity mirrors strategy_docs (project_id, slug); revision is the
# per-doc monotonic sequence. actor_id follows the same provenance-only,
# no-FK stance as updated_by_actor_id above.
STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {STRATEGY_DOC_REVISIONS_TABLE} (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  slug TEXT NOT NULL,
  revision BIGINT NOT NULL,
  content TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  byte_length BIGINT NOT NULL,
  source_operation TEXT NOT NULL,
  actor_id BIGINT,
  session_id TEXT,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_doc_revisions_doc_revision
  ON {STRATEGY_DOC_REVISIONS_TABLE}(project_id, slug, revision)
"""


__all__ = [
    "STRATEGY_DOCS_CREATE_TABLE_SQL",
    "STRATEGY_DOCS_TABLE",
    "STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL",
    "STRATEGY_DOC_REVISIONS_TABLE",
]
