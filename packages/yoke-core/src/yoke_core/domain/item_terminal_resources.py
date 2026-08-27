"""Atomic release of execution resources when an item becomes terminal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_worktrees import release_item_worktrees
from yoke_core.domain.strategy_execution import (
    active_strategy_doc_claim,
    release_strategy_doc_claim,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    WorkflowRuntime,
    load_item_workflow_runtime,
)
from yoke_core.domain.work_claim_targets import scope_int_sql


@dataclass(frozen=True)
class TerminalResourceReceipt:
    """Counts for resources released in the caller-owned transaction."""

    document_claim_released: bool = False
    ephemeral_environments_stopped: int = 0
    worktree_lanes_released: int = 0
    work_claims_released: int = 0
    migration_territories_released: int = 0
    holder_session_ids: tuple[str, ...] = ()


def terminal_stage_ids(runtime: WorkflowRuntime) -> frozenset[str]:
    """Return definition-owned and engine-owned terminal stage ids."""
    return runtime.terminal_stage_ids | ENGINE_TERMINAL_STAGE_IDS


def ensure_item_accepts_active_resources(conn: Any, item_id: int) -> None:
    """Reject active execution-resource creation for a terminal item.

    The caller must lock the item row before invoking this guard. Claim and
    worktree writers use that parent lock to serialize against the status
    transaction that both marks the item terminal and releases its resources.
    """
    from yoke_core.domain.workflow_item_binding_validation import (
        item_binding_runtime_state,
    )

    item_binding_runtime_state(conn, int(item_id))


def _lock_active_work_claims(conn: Any, item_id: int) -> list[dict[str, Any]]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    item_scope = scope_int_sql(conn, "scope", "item_id")
    epic_scope = scope_int_sql(conn, "scope", "epic_id")
    cursor = conn.execute(
        "SELECT id, session_id, target_kind, scope "
        "FROM work_claims WHERE released_at IS NULL AND "
        f"((target_kind='item' AND {item_scope}={marker}) OR "
        f"(target_kind='epic_task' AND {epic_scope}={marker})) "
        f"ORDER BY id{suffix}",
        (int(item_id), int(item_id)),
    )
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _release_active_work_claims(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
    successful_terminal: bool,
) -> tuple[int, tuple[str, ...]]:
    rows = _lock_active_work_claims(conn, int(item_id))
    if not rows:
        return 0, ()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    released_at = iso8601_now()
    release_reason = "completed" if successful_terminal else "released"
    release_intent = f"item-terminal:{target_status}"
    released = 0
    for row in rows:
        cursor = conn.execute(
            "UPDATE work_claims SET released_at="
            f"{marker}, release_reason={marker}, release_reason_intent={marker} "
            f"WHERE id={marker} AND released_at IS NULL",
            (
                released_at,
                release_reason,
                release_intent,
                int(row["id"]),
            ),
        )
        released += max(int(cursor.rowcount or 0), 0)
    holder_session_ids = tuple(sorted({str(row["session_id"]) for row in rows}))
    return released, holder_session_ids


def release_for_terminal_transition(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
    session_id: Optional[str],
    actor_id: Optional[int],
) -> TerminalResourceReceipt:
    """Release all item/task execution resources without committing.

    The item's status write and parent-row lock must already be present on
    ``conn``. No harness-session row is mutated here, so this function uses
    the safe item→claim suffix of the global session→item→claim lock order.
    """
    runtime = load_item_workflow_runtime(conn, int(item_id))
    terminals = terminal_stage_ids(runtime)
    if target_status not in terminals:
        return TerminalResourceReceipt()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT status FROM items WHERE id={marker}",
        (int(item_id),),
    ).fetchone()
    live_status = (
        str(row["status"] if hasattr(row, "keys") else row[0])
        if row is not None
        else ""
    )
    if live_status != target_status:
        raise RuntimeError(
            f"terminal cleanup expected item {item_id} at {target_status!r}; "
            f"found {live_status!r}"
        )

    document_released = False
    if active_strategy_doc_claim(conn, item_id=int(item_id)) is not None:
        release_strategy_doc_claim(
            conn,
            item_id=int(item_id),
            session_id=session_id or "",
            actor_id=actor_id,
            reason=f"lifecycle transition to {target_status}",
            terminal_lifecycle=True,
            commit=False,
        )
        document_released = True
    from yoke_core.domain.ephemeral_environment_item_binding import (
        stop_item_environments,
    )

    environments_stopped = stop_item_environments(
        conn,
        item_id=int(item_id),
    )
    lanes_released = release_item_worktrees(conn, item_id=int(item_id))
    work_claims_released, holder_session_ids = _release_active_work_claims(
        conn,
        item_id=int(item_id),
        target_status=target_status,
        successful_terminal=target_status in runtime.terminal_stage_ids,
    )
    from yoke_core.domain.migration_territory_claim import (
        release_for_terminal_item,
    )

    migration_lease_id = release_for_terminal_item(
        conn,
        item_id=int(item_id),
        holder_session_ids=holder_session_ids,
        target_status=target_status,
    )
    return TerminalResourceReceipt(
        document_claim_released=document_released,
        ephemeral_environments_stopped=environments_stopped,
        worktree_lanes_released=lanes_released,
        work_claims_released=work_claims_released,
        migration_territories_released=int(migration_lease_id is not None),
        holder_session_ids=tuple(
            sorted(
                {
                    *holder_session_ids,
                    *([session_id] if session_id else []),
                }
            )
        ),
    )


__all__ = [
    "TerminalResourceReceipt",
    "ensure_item_accepts_active_resources",
    "release_for_terminal_transition",
    "terminal_stage_ids",
]
