"""Atomic linking of Blitz items to their execution strategy documents."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.strategy_docs import get_doc
from yoke_core.domain.strategy_execution_state import (
    StrategyExecutionLinkError,
    _marker,
    _require_blitz_item,
    active_strategy_doc_claim,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from yoke_core.domain.workflow_item_binding_validation import (
    item_binding_runtime_state,
)


@rollback_workflow_binding_write_errors
def link_execution_document(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    slug: str,
    actor_id: Optional[int],
    session_id: Optional[str],
    commit: bool = True,
) -> dict[str, Any]:
    """Link exactly one execution document to one active Blitz item."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    item_binding_runtime_state(conn, int(item_id))
    item = _require_blitz_item(conn, item_id)
    if int(item["project_id"]) != int(project_id):
        raise StrategyExecutionLinkError(
            "the execution document must belong to the Blitz project"
        )
    get_doc(conn, int(project_id), slug)
    marker = _marker(conn)
    active = active_strategy_doc_claim(conn, item_id=int(item_id))
    if active is not None and str(active["strategy_doc_slug"]) != slug:
        raise StrategyExecutionLinkError(
            "an active Blitz cannot replace its claimed execution document"
        )
    linked_at = iso8601_now()
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_by_actor_id, "
        "linked_by_session_id, linked_at) "
        f"VALUES ({', '.join(marker for _ in range(6))}) "
        "ON CONFLICT(item_id) DO UPDATE SET "
        "project_id = EXCLUDED.project_id, "
        "strategy_doc_slug = EXCLUDED.strategy_doc_slug, "
        "linked_by_actor_id = EXCLUDED.linked_by_actor_id, "
        "linked_by_session_id = EXCLUDED.linked_by_session_id, "
        "linked_at = EXCLUDED.linked_at",
        (
            int(item_id),
            int(project_id),
            slug,
            actor_id,
            session_id,
            linked_at,
        ),
    )
    if commit:
        conn.commit()
    return {
        "item_id": int(item_id),
        "project_id": int(project_id),
        "slug": slug,
        "linked_at": linked_at,
    }


__all__ = ["link_execution_document"]
