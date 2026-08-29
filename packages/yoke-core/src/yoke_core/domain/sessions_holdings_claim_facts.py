"""Per-claim facts the session-holdings read batches into claim payloads.

A session holds several claims of the same kind at once, so every fact a
reader shows about one of them has to be read per claim. A singular
session-level field cannot describe more than the one claim it was
resolved for, and a card driven by one shows that claim correctly and
guesses at the rest. Both readers here answer that shape in one batched
query each: :func:`claimed_item_facts` for item claims, and
:func:`steered_document_slugs` for steering claims.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend


def param_marker(conn: Any) -> str:
    """The parameter placeholder this connection's dialect expects."""
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def clear_failed_read(conn: Any) -> None:
    """Clear an aborted transaction after a missing-relation read."""
    try:
        conn.rollback()
    except Exception:
        pass


def claimed_item_facts(
    conn: Any,
    item_ids: List[int],
) -> Dict[int, Dict[str, Any]]:
    """Describe each claimed item in one read, keyed by internal id.

    Values are the claim-payload shape itself — ``public_ref``,
    ``item_project_id``, ``item_project_sequence``, ``item_status``,
    ``item_workflow_id`` — so every item claim says what it is and how far
    along it is, not only the one the session's focus names. An id with no
    backing item row is absent; callers apply the display fallback.
    """
    distinct = list(dict.fromkeys(int(value) for value in item_ids))
    if not distinct:
        return {}
    marker = param_marker(conn)
    placeholders = ", ".join(marker for _ in distinct)
    try:
        rows = conn.execute(
            "SELECT i.id AS id, i.project_id AS project_id, i.title AS title, "
            "i.project_sequence AS project_sequence, i.status AS status, "
            "i.workflow_id AS workflow_id, p.public_item_prefix AS prefix "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders})",
            tuple(distinct),
        ).fetchall()
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return {}
    facts: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        facts[int(row["id"])] = {
            "public_ref": format_item_ref(
                None,
                row["prefix"],
                row["project_sequence"],
            ),
            "item_project_id": int(row["project_id"]),
            "item_project_sequence": int(row["project_sequence"]),
            "item_title": row["title"],
            "item_status": row["status"],
            "item_workflow_id": row["workflow_id"],
        }
    return facts


def steered_document_slugs(
    conn: Any,
    session_ids: Iterable[str],
) -> Dict[Tuple[str, int], List[str]]:
    """Strategy documents each session steers a project from.

    Keyed by ``(session_id, project_id)``, because a session steering
    several projects holds a document lock per project and the reader
    has to pair each project with its own documents. A pair with no
    locked document is absent rather than empty.
    """
    holders = list(dict.fromkeys(str(value) for value in session_ids if value))
    if not holders:
        return {}
    marker = param_marker(conn)
    placeholders = ", ".join(marker for _ in holders)
    try:
        rows = conn.execute(
            "SELECT owner_session_id, project_id, strategy_doc_slug "
            "FROM strategy_doc_claims WHERE owner_kind = 'session' "
            f"AND released_at IS NULL AND owner_session_id IN ({placeholders}) "
            "ORDER BY project_id, strategy_doc_slug",
            tuple(holders),
        ).fetchall()
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return {}
    grouped: Dict[Tuple[str, int], List[str]] = {}
    for row in rows:
        key = (str(row["owner_session_id"]), int(row["project_id"]))
        grouped.setdefault(key, []).append(str(row["strategy_doc_slug"]))
    return grouped


__all__ = [
    "claimed_item_facts",
    "clear_failed_read",
    "param_marker",
    "steered_document_slugs",
]
