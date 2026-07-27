"""Storage shape for the strategy-doc authority: doc rows + revision chain.

Declares the ``strategy_docs`` table (the per-project doc authority
:mod:`yoke_core.domain.strategy_docs` owns) and its append-only
``strategy_doc_revisions`` history, plus the one shared helper every
content writer calls to append a revision row.

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

from typing import Any, Optional

from yoke_core.domain.strategy_docs_header import content_sha256

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
  updated_at TEXT NOT NULL,
  updated_by_actor_id BIGINT,
  -- archived_at: nullable ISO timestamp. NULL = active (renders to
  -- .yoke/strategy/<slug>.md); a timestamp = archived (renders to
  -- .yoke/strategy/archive/<slug>.md). Flipped by strategy.doc.archive /
  -- strategy.doc.unarchive; the doc stays a full, editable corpus row.
  archived_at TEXT
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
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_doc_revisions_doc_revision
  ON {STRATEGY_DOC_REVISIONS_TABLE}(project_id, slug, revision)
"""


def record_doc_revision(
    conn: Any,
    project_id: int,
    slug: str,
    content: str,
    *,
    source_operation: str,
    actor_id: Optional[int],
    session_id: Optional[str] = None,
    created_at: str,
) -> int:
    """Append one revision row inside the caller's open transaction.

    Called between a strategy_docs content write and its commit so the
    snapshot lands (or rolls back) atomically with the row it mirrors.
    ``created_at`` is the write's freshly minted ``updated_at`` stamp,
    tying each revision to the exact doc state it snapshots. Returns
    the revision number assigned.

    MAX+1 is race-safe without extra locking: concurrent writers to the
    same doc serialize on the doc row itself (the CAS UPDATE's row lock,
    or the unique slug index for create), and the unique
    ``(project_id, slug, revision)`` index backstops the invariant.
    """
    row = conn.execute(
        f"SELECT COALESCE(MAX(revision), 0) + 1 AS next_revision "
        f"FROM {STRATEGY_DOC_REVISIONS_TABLE} "
        "WHERE project_id = %s AND slug = %s",
        (project_id, slug),
    ).fetchone()
    revision = int(row["next_revision"] if hasattr(row, "keys") else row[0])
    conn.execute(
        f"INSERT INTO {STRATEGY_DOC_REVISIONS_TABLE} "
        "(project_id, slug, revision, content, content_sha256, "
        "byte_length, source_operation, actor_id, session_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            project_id,
            slug,
            revision,
            content,
            content_sha256(content),
            len(content.encode("utf-8")),
            source_operation,
            actor_id,
            session_id,
            created_at,
        ),
    )
    return revision


__all__ = [
    "STRATEGY_DOCS_CREATE_TABLE_SQL",
    "STRATEGY_DOCS_TABLE",
    "STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL",
    "STRATEGY_DOC_REVISIONS_TABLE",
    "record_doc_revision",
]
