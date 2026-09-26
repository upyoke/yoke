"""Run success and member close-out settle together, or neither does.

A run whose shared gates passed used to commit ``succeeded`` first and close
its members one by one afterwards. A member whose close-out then refused was
left at its release wait under a green run — delivered by every record, done
by none, with a holder woken to repair what the release had already decided.

So before a run is left succeeded, every member it clears is asked whether
its close-out would land: the same close-out, every gate answered, nothing
written. Any refusal holds the run at its prior status with each member and
its reason named. Nothing is closed, released, or cleaned up, so every claim
and lane is exactly where it was for the repair and the re-drive.

The question has to be asked of a succeeded run, because each gate reads
delivery from committed rows on its own connection. The caller therefore
writes ``succeeded``, asks, and on refusal restores the run's prior status.
The one thing the question writes is the delivery rung each preview stamps;
a refusal restores those rows too, so a held run leaves no evidence claiming
a delivery that did not settle.
"""

from __future__ import annotations

from typing import Any, Optional


_STAMP_COLUMNS = (
    "rung_id",
    "target_status",
    "detail",
    "facts",
    "recorded_at",
    "recorded_by_session_id",
)


def _delivery_stamp(conn: Any, item_id: int) -> Optional[tuple]:
    row = conn.execute(
        f"SELECT {','.join(_STAMP_COLUMNS)} FROM item_gate_satisfactions "
        "WHERE item_id=%s AND obligation='delivery_evidence'",
        (int(item_id),),
    ).fetchone()
    return None if row is None else tuple(row)


def _restore_delivery_stamp(conn: Any, item_id: int, prior: Optional[tuple]) -> None:
    if prior is None:
        conn.execute(
            "DELETE FROM item_gate_satisfactions "
            "WHERE item_id=%s AND obligation='delivery_evidence'",
            (int(item_id),),
        )
        return
    assignments = ",".join(f"{column}=%s" for column in _STAMP_COLUMNS)
    conn.execute(
        f"UPDATE item_gate_satisfactions SET {assignments} "
        "WHERE item_id=%s AND obligation='delivery_evidence'",
        (*prior, int(item_id)),
    )


def member_close_out_refusal(conn: Any, run_id: str) -> Optional[str]:
    """Name every cleared member whose close-out would refuse, or ``None``.

    Call with the run's ``succeeded`` status committed. On a refusal the
    preview's delivery stamps are already restored when this returns.
    """
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        cleared_release_waits,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        close_out_satisfied_delivery_member,
    )

    members = cleared_release_waits(conn, run_id)
    priors = {int(m["item_id"]): _delivery_stamp(conn, m["item_id"]) for m in members}
    refused: list[str] = []
    for member in members:
        outcome = close_out_satisfied_delivery_member(
            conn,
            item_id=int(member["item_id"]),
            public_ref=str(member["public_ref"]),
            run_id=run_id,
            preview=True,
        )
        if outcome.applies and not outcome.ok:
            refused.append(f"{member['public_ref']}: {outcome.detail}")
    if not refused:
        return None
    for item_id, prior in priors.items():
        _restore_delivery_stamp(conn, item_id, prior)
    conn.commit()
    return (
        f"Error: cannot set status=succeeded -- {len(refused)} member "
        f"close-out(s) of run {run_id} would refuse, and run success and "
        f"member close-out settle together: {'; '.join(refused)}. The run "
        "keeps its prior status and every member keeps its claim and lane. "
        "Repair each named member, then re-drive completion under the "
        f"project deploy lock with `yoke deployment-runs update {run_id} "
        "status succeeded`."
    )


__all__ = ["member_close_out_refusal"]
