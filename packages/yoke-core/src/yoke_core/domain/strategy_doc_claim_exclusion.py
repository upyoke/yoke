"""Mutual exclusion between a document lock and the Blitz that executes it.

One strategy document has one holder. A coordinator holding the document
directly (a ``session``-owned claim) and a Blitz executing that same
document are two ways to be working it, and they must not both be live:
whoever holds the document decides what it says, and a Blitz claimed while
a coordinator still holds its document would execute prose the coordinator
is still rewriting.

The partial unique index on ``(project_id, strategy_doc_slug)`` already
keeps two *claims* apart. These readers cover the half the index cannot
see: a Blitz item is claimable before it acquires its document, and a
document lock must refuse while such a Blitz is still live.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.strategy_execution_state import (
    BLITZ_WORKFLOW_ID,
    _marker,
    _row,
    active_strategy_doc_claim,
    claim_holder_label,
)


def linked_document(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    """Return the execution document an item is bound to, if any."""
    marker = _marker(conn)
    return _row(
        conn.execute(
            "SELECT project_id, strategy_doc_slug FROM item_strategy_docs "
            f"WHERE item_id = {marker}",
            (int(item_id),),
        )
    )


def document_lock_holding_item(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    """Return the session-owned lock standing between an item and its document.

    Answers for any item: a work item with no execution document, or one
    whose document nobody holds directly, is not blocked by this rule.
    """
    link = linked_document(conn, int(item_id))
    if link is None:
        return None
    claim = active_strategy_doc_claim(
        conn,
        project_id=int(link["project_id"]),
        slug=str(link["strategy_doc_slug"]),
    )
    if claim is None or str(claim["owner_kind"]) != "session":
        return None
    return claim


def document_lock_refusal(conn: Any, item_id: int) -> Optional[str]:
    """Render why an item cannot be claimed while its document is held."""
    claim = document_lock_holding_item(conn, int(item_id))
    if claim is None:
        return None
    return (
        f"strategy document {claim['strategy_doc_slug']!r} is held by "
        f"{claim_holder_label(claim)}; that lock releases before this item "
        "can be claimed"
    )


def live_execution_for_document(
    conn: Any,
    *,
    project_id: int,
    slug: str,
) -> Optional[dict[str, Any]]:
    """Return a live Blitz standing between a document and a direct lock.

    Live means the document's own item-owned claim, or a non-terminal Blitz
    bound to the document — a Blitz that has not acquired its document yet
    still owns the right to.
    """
    claim = active_strategy_doc_claim(conn, project_id=int(project_id), slug=slug)
    if claim is not None and str(claim["owner_kind"]) == "item":
        return {
            "item_id": int(claim["owner_item_id"]),
            "item_ref": claim.get("item_ref"),
            "item_title": claim.get("item_title"),
            "item_status": claim.get("item_status"),
            "holds_document_claim": True,
        }
    return _non_terminal_linked_blitz(conn, project_id=int(project_id), slug=slug)


def _non_terminal_linked_blitz(
    conn: Any,
    *,
    project_id: int,
    slug: str,
) -> Optional[dict[str, Any]]:
    from yoke_contracts.item_ref import format_item_ref
    from yoke_core.domain.item_terminal_resources import terminal_stage_ids
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    marker = _marker(conn)
    rows = conn.execute(
        "SELECT i.id, i.title, i.status, i.project_sequence, "
        "p.slug AS project_slug, p.public_item_prefix "
        "FROM item_strategy_docs l "
        "JOIN items i ON i.id = l.item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE l.project_id = {marker} AND l.strategy_doc_slug = {marker} "
        f"AND i.workflow_id = {marker} "
        "ORDER BY i.id",
        (int(project_id), slug, BLITZ_WORKFLOW_ID),
    ).fetchall()
    for row in rows:
        values = dict(row)
        runtime = load_item_workflow_runtime(conn, int(values["id"]))
        if str(values["status"]) in terminal_stage_ids(runtime):
            continue
        return {
            "item_id": int(values["id"]),
            "item_ref": format_item_ref(
                values["project_slug"],
                values["public_item_prefix"],
                int(values["project_sequence"]),
            ),
            "item_title": values["title"],
            "item_status": values["status"],
            "holds_document_claim": False,
        }
    return None


def live_execution_refusal(
    conn: Any,
    *,
    project_id: int,
    slug: str,
) -> Optional[str]:
    """Render why a document cannot be locked while a Blitz still executes it."""
    execution = live_execution_for_document(
        conn,
        project_id=int(project_id),
        slug=slug,
    )
    if execution is None:
        return None
    reference = execution["item_ref"] or f"item {execution['item_id']}"
    held = (
        "holds the document claim"
        if execution["holds_document_claim"]
        else f"is live at {execution['item_status']}"
    )
    return (
        f"strategy document {slug!r} executes as Blitz {reference} "
        f"({execution['item_title']}), which {held}; that Blitz reaches a "
        "terminal stage before the document can be locked directly"
    )


__all__ = [
    "document_lock_holding_item",
    "document_lock_refusal",
    "linked_document",
    "live_execution_for_document",
    "live_execution_refusal",
]
