"""DB helpers for worktree creation."""

from __future__ import annotations

from typing import Iterable, Optional, Tuple


def persist_item_worktrees(
    item_id: int,
    lanes: Iterable[Tuple[str, str, str]],
    db_path: Optional[str],
) -> None:
    """Best-effort universal-lane write with a legacy primary projection."""
    from yoke_core.domain.db_helpers import connect

    lane_rows = list(lanes)
    if not lane_rows:
        return
    try:
        conn = connect(db_path)
    except Exception:  # noqa: BLE001 — best-effort
        return
    try:
        from yoke_core.domain import db_backend
        from yoke_core.domain.item_worktrees import record_item_worktree
        from yoke_core.domain.schema_common import _table_exists
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            f"UPDATE items SET worktree = {p} WHERE id = {p}",
            (lane_rows[0][0], int(item_id)),
        )
        if _table_exists(conn, "item_worktrees"):
            session_id = resolve_ambient_session_id()
            for branch, path, lane_role in lane_rows:
                record_item_worktree(
                    conn,
                    item_id=int(item_id),
                    branch=branch,
                    path=path,
                    lane_role=lane_role,
                    session_id=session_id,
                )
        conn.commit()
    except Exception:  # noqa: BLE001 — best-effort
        pass
    finally:
        conn.close()


def persist_item_worktree(
    item_id: int,
    branch: str,
    db_path: Optional[str],
) -> None:
    """Compatibility wrapper for a single implementation lane."""
    from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION

    persist_item_worktrees(
        item_id,
        [(branch, "", LANE_IMPLEMENTATION)],
        db_path,
    )


def check_path_claim_gate(item_id: int, db_path: Optional[str]) -> Optional[str]:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.path_claims_gate import (
        PathClaimGateBlocked,
        check_worktree_create_gate,
    )

    gate_conn = connect(db_path)
    try:
        check_worktree_create_gate(gate_conn, int(item_id))
    except PathClaimGateBlocked as exc:
        return str(exc)
    finally:
        gate_conn.close()
    return None


__all__ = [
    "check_path_claim_gate",
    "persist_item_worktree",
    "persist_item_worktrees",
]
