"""Append a strategy document revision in its content writer's transaction."""

from yoke_core.domain.db_helpers import instant_parameter
from datetime import datetime
from yoke_contracts.timestamps import parse_instant

from typing import Any, Optional

from yoke_core.domain.strategy_docs_header import content_sha256
from yoke_core.domain.strategy_docs_schema import STRATEGY_DOC_REVISIONS_TABLE


def record_doc_revision(
    conn: Any,
    project_id: int,
    slug: str,
    content: str,
    *,
    source_operation: str,
    actor_id: Optional[int],
    session_id: Optional[str] = None,
    created_at: datetime | str,
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
            instant_parameter(conn, parse_instant(created_at)),
        ),
    )
    return revision

