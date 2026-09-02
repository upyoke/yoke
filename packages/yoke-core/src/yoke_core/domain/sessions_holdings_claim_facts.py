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

from typing import Any, Dict, Iterable, List

from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.session_holdings import pair_steering_document_slugs
from yoke_core.domain import db_backend
from yoke_core.domain.work_claim_targets import scope_int_sql


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
    claim_ids: Iterable[int],
) -> Dict[int, List[str]]:
    """Strategy documents paired with each steering claim's hold window.

    Current steering claims pair only with current document locks. Released
    claims pair with released locks from the same session and project whose
    hold windows overlapped. Keying by claim id keeps repeated steering holds
    for one session and project temporally distinct.
    """
    distinct = list(dict.fromkeys(int(value) for value in claim_ids))
    if not distinct:
        return {}
    marker = param_marker(conn)
    placeholders = ", ".join(marker for _ in distinct)
    project_id = scope_int_sql(conn, "claim.scope", "project_id")
    try:
        rows = conn.execute(
            "SELECT claim.id AS claim_id, "
            "claim.claimed_at AS claim_claimed_at, "
            "claim.released_at AS claim_released_at, "
            "doc.strategy_doc_slug AS strategy_doc_slug, "
            "doc.registered_at AS doc_registered_at, "
            "doc.released_at AS doc_released_at "
            "FROM work_claims claim LEFT JOIN strategy_doc_claims doc "
            "ON doc.owner_kind = 'session' "
            "AND doc.owner_session_id = claim.session_id "
            f"AND doc.project_id = {project_id} "
            "WHERE claim.target_kind = 'steering' "
            f"AND claim.id IN ({placeholders}) "
            "ORDER BY claim.id, doc.strategy_doc_slug",
            tuple(distinct),
        ).fetchall()
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return {}
    paired = pair_steering_document_slugs(dict(row) for row in rows)
    return {int(claim_id): slugs for claim_id, slugs in paired.items()}


__all__ = [
    "claimed_item_facts",
    "clear_failed_read",
    "param_marker",
    "steered_document_slugs",
]
