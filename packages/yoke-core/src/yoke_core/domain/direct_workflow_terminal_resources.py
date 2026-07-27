"""Terminal lifecycle cleanup for direct-workflow execution resources."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.item_worktrees import release_item_worktrees
from yoke_core.domain.strategy_execution import (
    active_strategy_doc_claim,
    release_strategy_doc_claim,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

_TERMINAL_TARGETS = frozenset({"done", "cancelled", "stopped"})
_DIRECT_WORKFLOWS = frozenset({"blitz", "dash"})


def release_for_transition(
    *,
    item_id: int,
    target_status: str,
    session_id: str,
    actor_id: Optional[int],
) -> dict[str, object]:
    """Release document ownership and registered lanes after terminal status."""
    if target_status not in _TERMINAL_TARGETS:
        return {"document_claim_released": False, "worktree_lanes_released": 0}
    conn = connect()
    try:
        workflow = load_item_workflow_runtime(conn, int(item_id))
        if workflow.workflow_id not in _DIRECT_WORKFLOWS:
            return {
                "document_claim_released": False,
                "worktree_lanes_released": 0,
            }
        document_released = False
        if (
            workflow.workflow_id == "blitz"
            and active_strategy_doc_claim(conn, item_id=int(item_id)) is not None
        ):
            release_strategy_doc_claim(
                conn,
                item_id=int(item_id),
                session_id=session_id,
                actor_id=actor_id,
                reason=f"lifecycle transition to {target_status}",
            )
            document_released = True
        released_lanes = release_item_worktrees(conn, item_id=int(item_id))
        conn.commit()
        return {
            "document_claim_released": document_released,
            "worktree_lanes_released": released_lanes,
        }
    finally:
        conn.close()


__all__ = ["release_for_transition"]
