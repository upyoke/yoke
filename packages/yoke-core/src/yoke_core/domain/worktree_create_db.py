"""DB helpers for worktree creation."""

from __future__ import annotations

from typing import Optional


def persist_item_worktree(
    item_id: int, branch: str, db_path: Optional[str],
) -> None:
    """Best-effort ``items.worktree`` write; ``lint_session_cwd`` reads it."""
    from yoke_core.domain.db_helpers import connect

    try:
        conn = connect(db_path)
    except Exception:  # noqa: BLE001 — best-effort
        return
    try:
        from yoke_core.domain import db_backend

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            f"UPDATE items SET worktree = {p} WHERE id = {p}",
            (branch, int(item_id)),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 — best-effort
        pass
    finally:
        conn.close()


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


__all__ = ["check_path_claim_gate", "persist_item_worktree"]
