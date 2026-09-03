"""Which work belongs to a document-scoped steering seat.

A seat narrowed to a strategy document steers that document's work and
nothing else, so something has to say which items those are. The answer is
the item-to-document link in ``item_strategy_docs``: an item is a member of
the document it is linked to, whether that link was written by
``strategy.execution.link`` or named at intake. Nothing else confers
membership, so a seat's coverage is a fact anyone can read rather than a
judgment the seat makes about titles.

Membership is read live, never cached on the message or the report. A link
written after a report was addressed still lands with the seat that covers
it now, which is the whole point of addressing a seat by role.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.work_claim_scope_shape import STEERING_DOCUMENT_KEY

LINK_TABLE = "item_strategy_docs"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def scope_document(scope: Mapping[str, Any]) -> Optional[str]:
    """The strategy document a steering scope is narrowed to, if any."""
    value = dict(scope).get(STEERING_DOCUMENT_KEY)
    return str(value) if value else None


def item_document_slug(conn: Any, item_id: int) -> Optional[str]:
    """The strategy document one item is linked to, if any.

    A universe whose storage predates the link table simply has no linked
    item, so this answers ``None`` there rather than failing the read that
    every steering address depends on.
    """
    if not _table_exists(conn, LINK_TABLE):
        return None
    row = conn.execute(
        f"SELECT strategy_doc_slug FROM {LINK_TABLE} "
        f"WHERE item_id = {_marker(conn)}",
        (int(item_id),),
    ).fetchone()
    return None if row is None else str(dict(row)["strategy_doc_slug"])


def item_coverage_target(
    conn: Any,
    *,
    project_id: int,
    item_id: Optional[int],
) -> dict[str, Any]:
    """Describe one piece of work the way the coverage rule reads it.

    The project is always known; the item and its document are the finer
    facts a narrowed seat keys on. Work with no item, or an item linked to
    no document, carries no document fact, so only a project-wide seat
    covers it.
    """
    target: dict[str, Any] = {"project_id": int(project_id)}
    if item_id is None:
        return target
    target["item_id"] = int(item_id)
    document = item_document_slug(conn, int(item_id))
    if document is not None:
        target[STEERING_DOCUMENT_KEY] = document
    return target


def document_member_item_ids(
    conn: Any,
    *,
    project_id: int,
    document: str,
) -> set[int]:
    """Every item in this project linked to ``document``."""
    if not _table_exists(conn, LINK_TABLE):
        return set()
    marker = _marker(conn)
    rows = conn.execute(
        f"SELECT item_id FROM {LINK_TABLE} "
        f"WHERE project_id = {marker} AND strategy_doc_slug = {marker}",
        (int(project_id), str(document)),
    ).fetchall()
    return {int(dict(row)["item_id"]) for row in rows}


def scope_member_item_ids(
    conn: Any,
    scope: Mapping[str, Any],
) -> Optional[set[int]]:
    """The items one steering scope covers, or ``None`` for the whole project.

    ``None`` is not "no members": it is the project-wide seat, which has no
    item filter at all. Callers that treat it as an empty set hide every
    item from the seat that owns them.
    """
    document = scope_document(scope)
    if document is None:
        return None
    project_id = dict(scope).get("project_id")
    if project_id is None:
        return set()
    return document_member_item_ids(
        conn,
        project_id=int(project_id),
        document=document,
    )


__all__ = [
    "LINK_TABLE",
    "document_member_item_ids",
    "item_coverage_target",
    "item_document_slug",
    "scope_document",
    "scope_member_item_ids",
]
