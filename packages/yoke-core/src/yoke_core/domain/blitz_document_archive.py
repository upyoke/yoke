"""Archive a Blitz execution document inside its done transaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend, strategy_docs
from yoke_core.domain.strategy_doc_claim_exclusion import (
    linked_document,
    live_execution_for_document,
)
from yoke_core.domain.strategy_docs_schema import STRATEGY_DOCS_TABLE
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


BLITZ_DOCUMENT_ARCHIVE_FAILURE = "GATE_BLITZ_DOCUMENT_ARCHIVE_FAILED"


class BlitzDocumentArchiveError(RuntimeError):
    """A completed Blitz could not atomically retire its execution doc."""

    code = BLITZ_DOCUMENT_ARCHIVE_FAILURE


@dataclass(frozen=True)
class BlitzDocumentArchiveReceipt:
    """Result of the transaction-owned execution-document archive step."""

    slug: str
    changed: bool
    retained_for_item_ref: Optional[str] = None


def _archive_without_commit(
    conn: Any,
    *,
    project_id: int,
    slug: str,
) -> bool:
    """Stamp ``archived_at`` without ending the caller-owned transaction."""
    doc = strategy_docs.get_doc(conn, int(project_id), slug)
    if doc["archived_at"] is not None:
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    cursor = conn.execute(
        f"UPDATE {STRATEGY_DOCS_TABLE} "
        f"SET archived_at = {marker} "
        f"WHERE project_id = {marker} AND slug = {marker} "
        "AND archived_at IS NULL",
        (strategy_docs.next_updated_at(), int(project_id), slug),
    )
    return int(cursor.rowcount or 0) > 0


def archive_completed_blitz_document(
    conn: Any,
    *,
    item_id: int,
) -> Optional[BlitzDocumentArchiveReceipt]:
    """Archive one completed Blitz's linked doc, retaining shared live docs.

    The caller invokes this after terminal resource release but before commit.
    That makes the current Blitz invisible to the live-execution reader while
    preserving another non-terminal Blitz's right to the same document.
    """
    slug = "<linked execution document>"
    try:
        runtime = load_item_workflow_runtime(conn, int(item_id))
        if runtime.workflow_id != "blitz":
            return None
        link = linked_document(conn, int(item_id))
        if link is None:
            return None
        project_id = int(link["project_id"])
        slug = str(link["strategy_doc_slug"])
        live = live_execution_for_document(
            conn,
            project_id=project_id,
            slug=slug,
        )
        if live is not None:
            if int(live["item_id"]) == int(item_id):
                raise BlitzDocumentArchiveError(
                    "the completed Blitz still owns its execution-document claim"
                )
            retained_ref = str(live.get("public_ref") or f"item {live['item_id']}")
            return BlitzDocumentArchiveReceipt(
                slug=slug,
                changed=False,
                retained_for_item_ref=retained_ref,
            )
        return BlitzDocumentArchiveReceipt(
            slug=slug,
            changed=_archive_without_commit(
                conn,
                project_id=project_id,
                slug=slug,
            ),
        )
    except BlitzDocumentArchiveError as exc:
        cause = str(exc)
    except Exception as exc:  # noqa: BLE001 - translate the transaction failure
        cause = str(exc)
    raise BlitzDocumentArchiveError(
        f"{BLITZ_DOCUMENT_ARCHIVE_FAILURE}: could not archive strategy "
        f"document {slug!r} while completing Blitz item {item_id}; the done "
        "transition was rolled back. Recovery: restore strategy-document "
        "write availability, then retry the reviewing-implementation -> done "
        f"transition. Cause: {cause}"
    )


__all__ = [
    "BLITZ_DOCUMENT_ARCHIVE_FAILURE",
    "BlitzDocumentArchiveError",
    "BlitzDocumentArchiveReceipt",
    "archive_completed_blitz_document",
]
