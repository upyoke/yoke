"""Row-lock primitives shared by deployment-run mutation commands."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings

_RUN_MEMBERSHIP_LOCK_RETRIES = 5


def lock_run(conn, run_id: str) -> Optional[str]:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT status FROM deployment_runs WHERE id=%s{suffix}",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["status"] if hasattr(row, "keys") else row[0])


def _run_item_ids(conn, run_id: str) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return tuple(
        int(row["item_id"]) if hasattr(row, "keys") else int(row[0]) for row in rows
    )


def lock_run_with_stable_membership(
    conn,
    run_id: str,
) -> tuple[Optional[str], tuple[int, ...]]:
    """Lock workflow bindings before the run and reject a stale member snapshot."""
    for _attempt in range(_RUN_MEMBERSHIP_LOCK_RETRIES):
        item_ids = _run_item_ids(conn, run_id)
        lock_item_workflow_bindings(conn, item_ids)
        status = lock_run(conn, run_id)
        if status is None:
            return None, ()
        if _run_item_ids(conn, run_id) == item_ids:
            return status, item_ids
        conn.rollback()
    raise RuntimeError(
        f"deployment run '{run_id}' membership changed repeatedly while locking"
    )


__all__ = ["lock_run", "lock_run_with_stable_membership"]
