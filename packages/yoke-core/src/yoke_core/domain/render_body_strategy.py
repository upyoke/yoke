"""Strategy-document body-section renderer.

Sibling of :mod:`render_body`. Emits one concise ``## Strategy``
instruction when the item has an explicit ``item_strategy_docs``
row. The link already names the document by owning project plus slug,
including a document that belongs to a different project than the item.
Unlinked items emit nothing — the renderer never infers CURRENT-PLAN
or a steering-session association.

The section tells the executor to read that document before executing
and names the existing retrieval command
(``yoke strategy doc get <slug> --project <project>``). It does not
embed document content or write anything back into stored item prose.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.schema_common import _table_exists as _schema_table_exists


STRATEGY_REFERENCE_HEADING = "## Strategy"


def strategy_doc_get_command(project_slug: str, doc_slug: str) -> str:
    """Return the registered retrieval command for one strategy doc."""
    return f"yoke strategy doc get {doc_slug} --project {project_slug}"


def strategy_reference_instruction(project_slug: str, doc_slug: str) -> str:
    """Return the mandatory pre-execution instruction for a linked doc."""
    command = strategy_doc_get_command(project_slug, doc_slug)
    return (
        f"Before executing this item, read strategy "
        f"{project_slug}/{doc_slug}: `{command}`"
    )


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _linked_strategy_doc(
    conn: Any,
    item_id: int,
) -> Optional[tuple[str, str]]:
    """Return ``(project_slug, doc_slug)`` for the item's explicit link."""
    if not _schema_table_exists(conn, "item_strategy_docs"):
        return None
    if not _schema_table_exists(conn, "projects"):
        return None
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT p.slug AS project_slug, l.strategy_doc_slug "
        "FROM item_strategy_docs l "
        "JOIN projects p ON p.id = l.project_id "
        f"WHERE l.item_id = {p}",
        (int(item_id),),
    )
    if row is None:
        return None
    if hasattr(row, "keys"):
        project = str(row["project_slug"] or "").strip()
        slug = str(row["strategy_doc_slug"] or "").strip()
    else:
        project = str(row[0] or "").strip()
        slug = str(row[1] or "").strip()
    if not project or not slug:
        return None
    return (project, slug)


def render_strategy_reference_section(conn: Any, item_id: int) -> str:
    """Return the ``## Strategy`` section, or '' when the item is unlinked."""
    link = _linked_strategy_doc(conn, item_id)
    if link is None:
        return ""
    project_slug, doc_slug = link
    return "\n".join(
        (
            STRATEGY_REFERENCE_HEADING,
            "",
            strategy_reference_instruction(project_slug, doc_slug),
        )
    )


__all__ = [
    "STRATEGY_REFERENCE_HEADING",
    "render_strategy_reference_section",
    "strategy_doc_get_command",
    "strategy_reference_instruction",
]
