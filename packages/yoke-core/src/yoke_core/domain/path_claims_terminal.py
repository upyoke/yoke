"""Terminal path-claim release and cancellation mutations."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.workflow_item_binding_lock import (
    lock_path_claim_workflow_binding,
    rollback_workflow_binding_write_errors,
)


@rollback_workflow_binding_write_errors
def release(
    conn: Any,
    *,
    claim_id: int,
    reason: str,
    commit: bool = True,
) -> None:
    """Release the door lock idempotently. Cancelled claims reject."""
    from yoke_core.domain.path_claims import (
        IllegalTransition,
        _fetch_claim,
        _now,
        _p,
    )

    lock_path_claim_workflow_binding(conn, claim_id)
    row = _fetch_claim(conn, claim_id)
    state = row["state"]
    if state == "released":
        if commit:
            conn.commit()
        return
    if state == "cancelled":
        raise IllegalTransition(f"cannot release claim {claim_id} after cancel")
    conn.execute(
        f"UPDATE path_claims SET state='released', released_at={_p(conn)}, "
        f"release_reason={_p(conn)} WHERE id = {_p(conn)}",
        (_now(), reason, claim_id),
    )
    if commit:
        conn.commit()


@rollback_workflow_binding_write_errors
def cancel(
    conn: Any,
    *,
    claim_id: int,
    reason: str,
    commit: bool = True,
) -> None:
    """Cancel a non-terminal claim idempotently. Released claims reject."""
    from yoke_core.domain.path_claims import (
        IllegalTransition,
        _fetch_claim,
        _now,
        _p,
    )

    lock_path_claim_workflow_binding(conn, claim_id)
    row = _fetch_claim(conn, claim_id)
    state = row["state"]
    if state == "cancelled":
        if commit:
            conn.commit()
        return
    if state == "released":
        raise IllegalTransition(f"cannot cancel claim {claim_id} after release")
    target_ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT target_id FROM path_claim_targets WHERE claim_id = {_p(conn)}",
            (claim_id,),
        )
    ]
    conn.execute(
        f"UPDATE path_claims SET state='cancelled', cancelled_at={_p(conn)}, "
        f"cancel_reason={_p(conn)} WHERE id = {_p(conn)}",
        (_now(), reason, claim_id),
    )
    from yoke_core.domain.path_targets_materialization import (
        abandon_planned_targets_without_open_claim,
    )

    abandon_planned_targets_without_open_claim(
        conn,
        target_ids=target_ids,
        reason=reason,
    )
    if commit:
        conn.commit()


__all__ = ["cancel", "release"]
