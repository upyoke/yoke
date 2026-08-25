"""Acquisition, authorization, and release of item-owned document claims."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.strategy_execution_state import (
    StrategyDocClaimAuthorizationError,
    StrategyDocClaimConflictError,
    StrategyExecutionLinkError,
    _active_item_claim,
    _marker,
    _require_blitz_item,
    _row,
    active_strategy_doc_claim,
    claim_holder_label,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from yoke_core.domain.workflow_item_binding_validation import (
    item_binding_runtime_state,
)


@rollback_workflow_binding_write_errors
def acquire_strategy_doc_claim(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    actor_id: Optional[int],
    commit: bool = True,
) -> dict[str, Any]:
    """Atomically acquire the linked document for the active Blitz item."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    item_binding_runtime_state(conn, int(item_id))
    _require_blitz_item(conn, item_id)
    item_claim = _active_item_claim(conn, item_id)
    if item_claim is None or str(item_claim["session_id"]) != session_id:
        raise StrategyDocClaimAuthorizationError(
            f"session {session_id!r} does not hold item {item_id}'s active claim"
        )
    marker = _marker(conn)
    link = _row(
        conn.execute(
            "SELECT project_id, strategy_doc_slug FROM item_strategy_docs "
            f"WHERE item_id = {marker}",
            (int(item_id),),
        )
    )
    if link is None:
        raise StrategyExecutionLinkError(
            f"Blitz item {item_id} has no execution document"
        )
    registered_at = iso8601_now()
    inserted = _row(
        conn.execute(
            "INSERT INTO strategy_doc_claims "
            "(project_id, strategy_doc_slug, owner_kind, owner_item_id, "
            "registered_by_actor_id, registered_by_session_id, "
            "registered_at) "
            f"VALUES ({marker}, {marker}, 'item', {marker}, "
            f"{marker}, {marker}, {marker}) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (
                int(link["project_id"]),
                str(link["strategy_doc_slug"]),
                int(item_id),
                actor_id,
                session_id,
                registered_at,
            ),
        )
    )
    if inserted is None:
        holder = active_strategy_doc_claim(
            conn,
            project_id=int(link["project_id"]),
            slug=str(link["strategy_doc_slug"]),
        )
        if holder is not None and holder["owner_item_id"] is not None and (
            int(holder["owner_item_id"]) == int(item_id)
        ):
            if commit:
                conn.commit()
            return holder
        label = (
            claim_holder_label(holder)
            if holder is not None
            else "another active holder"
        )
        raise StrategyDocClaimConflictError(
            f"strategy document {link['strategy_doc_slug']!r} is held by {label}"
        )
    claim = active_strategy_doc_claim(conn, item_id=int(item_id)) or {}
    if commit:
        conn.commit()
    return claim


def authorize_strategy_doc_write(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    session_id: str,
) -> bool:
    """Authorize a claimed doc write; return False when no claim exists.

    A False result tells the caller to apply its ordinary process-claim
    boundary. An active execution claim replaces that boundary: only the
    session currently holding the owning Blitz's item claim may revise it.
    """
    claim = active_strategy_doc_claim(
        conn,
        project_id=int(project_id),
        slug=slug,
    )
    if claim is None:
        return False
    if str(claim["owner_kind"]) == "session":
        if str(claim["owner_session_id"]) == session_id:
            return True
        raise StrategyDocClaimAuthorizationError(
            f"strategy document {slug!r} is held by "
            f"{claim_holder_label(claim)}; only that session may revise it"
        )
    item_claim = _active_item_claim(conn, int(claim["owner_item_id"]))
    if item_claim is None or str(item_claim["session_id"]) != session_id:
        raise StrategyDocClaimAuthorizationError(
            f"strategy document {slug!r} is owned by Blitz item "
            f"{claim['owner_item_id']}; only the session holding that "
            "item's active claim may revise it"
        )
    return True


@rollback_workflow_binding_write_errors
def release_strategy_doc_claim(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    actor_id: Optional[int],
    break_glass: bool = False,
    reason: Optional[str] = None,
    terminal_lifecycle: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    """Release one active item-owned claim under the parent item lock."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    claim = active_strategy_doc_claim(conn, item_id=int(item_id))
    if claim is None:
        raise StrategyExecutionLinkError(
            f"item {item_id} has no active strategy-document claim"
        )
    if break_glass and terminal_lifecycle:
        raise StrategyDocClaimAuthorizationError(
            "terminal lifecycle release cannot also be break-glass"
        )
    if terminal_lifecycle:
        from yoke_core.domain.item_terminal_resources import (
            terminal_stage_ids,
        )
        from yoke_core.domain.workflow_runtime import (
            load_item_workflow_runtime,
        )

        marker = _marker(conn)
        item_row = _row(
            conn.execute(
                f"SELECT status FROM items WHERE id = {marker}",
                (int(item_id),),
            )
        )
        runtime = load_item_workflow_runtime(conn, int(item_id))
        if item_row is None or str(item_row["status"]) not in terminal_stage_ids(
            runtime
        ):
            raise StrategyDocClaimAuthorizationError(
                "terminal lifecycle release requires a terminal item"
            )
    elif break_glass:
        if not str(reason or "").strip():
            raise StrategyDocClaimAuthorizationError(
                "break-glass release requires a durable reason"
            )
    else:
        item_claim = _active_item_claim(conn, item_id)
        if item_claim is None or str(item_claim["session_id"]) != session_id:
            raise StrategyDocClaimAuthorizationError(
                "normal release requires the session holding the item claim"
            )
    released_at = iso8601_now()
    marker = _marker(conn)
    cursor = conn.execute(
        "UPDATE strategy_doc_claims "
        f"SET released_by_actor_id = {marker}, "
        f"released_by_session_id = {marker}, released_at = {marker}, "
        f"release_mode = {marker}, release_reason = {marker} "
        f"WHERE id = {marker} AND released_at IS NULL",
        (
            actor_id,
            session_id,
            released_at,
            "break_glass" if break_glass else "normal",
            str(reason or "lifecycle release"),
            int(claim["id"]),
        ),
    )
    if int(cursor.rowcount or 0) != 1:
        raise StrategyExecutionLinkError(
            f"item {item_id}'s strategy-document claim is no longer active"
        )
    if commit:
        conn.commit()
    return {
        "claim_id": int(claim["id"]),
        "item_id": int(item_id),
        "slug": str(claim["strategy_doc_slug"]),
        "released_at": released_at,
        "release_mode": "break_glass" if break_glass else "normal",
    }


__all__ = [
    "acquire_strategy_doc_claim",
    "authorize_strategy_doc_write",
    "release_strategy_doc_claim",
]
