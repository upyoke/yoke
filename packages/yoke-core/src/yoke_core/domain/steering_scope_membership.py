"""Which work belongs to a document-scoped steering seat.

A seat narrowed to a strategy document steers that document's work and
nothing else, so something has to say which items those are. The answer is
the item-to-document link in ``item_strategy_docs``: an item is a member of
the document it is linked to, whether that link was written by
``strategy.execution.link`` or named at intake. The link names the
document's owning project, so membership is cross-project. Nothing else
confers membership, so a seat's coverage is a fact anyone can read rather
than a judgment the seat makes about titles.

A project-wide seat is not "every item in the project": it covers unlinked
items and items linked to that project's CURRENT-PLAN. Other linked items
are the matching document seat's, or unattended.

Membership is read live, never cached on the message or the report. A link
written after a report was addressed still lands with the seat that covers
it now, which is the whole point of addressing a seat by role.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.steering_scope_coverage import (
    DOCUMENT_PROJECT_KEY,
    PROJECT_KEY,
)
from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG
from yoke_core.domain.work_claim_scope_shape import STEERING_DOCUMENT_KEY

LINK_TABLE = "item_strategy_docs"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def scope_document(scope: Mapping[str, Any]) -> Optional[str]:
    """The strategy document a steering scope is narrowed to, if any."""
    value = dict(scope).get(STEERING_DOCUMENT_KEY)
    return str(value) if value else None


def item_document_link(conn: Any, item_id: int) -> Optional[tuple[int, str]]:
    """Owning project plus slug of the document one item is linked to."""
    if not _table_exists(conn, LINK_TABLE):
        return None
    row = conn.execute(
        f"SELECT project_id, strategy_doc_slug FROM {LINK_TABLE} "
        f"WHERE item_id = {_marker(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    return int(record["project_id"]), str(record["strategy_doc_slug"])


def item_document_slug(conn: Any, item_id: int) -> Optional[str]:
    """The strategy document one item is linked to, if any.

    A universe whose storage predates the link table simply has no linked
    item, so this answers ``None`` there rather than failing the read that
    every steering address depends on.
    """
    link = item_document_link(conn, item_id)
    return None if link is None else link[1]


def apply_item_document(
    conn: Any, target: dict[str, Any], item_id: int
) -> dict[str, Any]:
    """Add live document identity onto a coverage target, if the item is linked."""
    link = item_document_link(conn, int(item_id))
    if link is None:
        return target
    target[DOCUMENT_PROJECT_KEY] = link[0]
    target[STEERING_DOCUMENT_KEY] = link[1]
    return target


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
    target: dict[str, Any] = {PROJECT_KEY: int(project_id)}
    if item_id is None:
        return target
    target["item_id"] = int(item_id)
    return apply_item_document(conn, target, int(item_id))


def project_coverage_item_ids(conn: Any, project_id: int) -> Optional[set[int]]:
    """Items a project-wide seat covers, or ``None`` when links do not exist.

    ``None`` is not an empty set: it means there is no link table, so every
    item in the project still belongs to the project seat.
    """
    if not _table_exists(conn, LINK_TABLE):
        return None
    if not _table_exists(conn, "items"):
        return set()
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT i.id AS item_id FROM items i "
        f"LEFT JOIN {LINK_TABLE} l ON l.item_id = i.id "
        f"WHERE i.project_id = {marker} AND ("
        "l.item_id IS NULL OR "
        f"(l.project_id = {marker} AND l.strategy_doc_slug = {marker}))",
        (int(project_id), int(project_id), NEAR_TERM_PLAN_SLUG),
    ).fetchall()
    return {int(dict(row)["item_id"]) for row in rows}


def document_member_item_ids(
    conn: Any,
    *,
    project_id: int,
    document: str,
) -> set[int]:
    """Every item linked to this owning-project-plus-slug document."""
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
    """The items one steering scope covers, or ``None`` when unfiltered.

    ``None`` remains the pre-link-table whole-project seat. Once links
    exist, a project-wide seat returns the unlinked plus CURRENT-PLAN set
    so AREA-PLAN members are not treated as this seat's work.
    """
    document = scope_document(scope)
    project_id = dict(scope).get(PROJECT_KEY)
    if project_id is None:
        return set()
    if document is None:
        return project_coverage_item_ids(conn, int(project_id))
    return document_member_item_ids(
        conn,
        project_id=int(project_id),
        document=document,
    )


__all__ = [
    "LINK_TABLE",
    "apply_item_document",
    "document_member_item_ids",
    "item_coverage_target",
    "item_document_link",
    "item_document_slug",
    "project_coverage_item_ids",
    "scope_document",
    "scope_member_item_ids",
]
