"""A run reads succeeded only after every cleared member has closed.

A run whose shared gates passed used to commit ``succeeded`` and close its
members afterwards, so any refusal, failed write, or interrupted process in
between left a green run over members still at their release wait.

Settlement reverses that order through one durable, non-terminal state. The
run stays ``executing`` and records ``settling_at``; completion authority
reads a settling run as delivered, so each member's own done gates can pass.
Every cleared member is then closed for real, each committed on its own. Only
when none is left does the caller write ``succeeded``.

Anything that stops settlement part way leaves exactly that state behind: the
run ``executing`` and settling, the members that closed done, and every other
member at its release wait with its claim and lane. Re-driving ``status
succeeded`` replays settlement from there — a member already done is no longer
at its wait, so nothing is closed twice.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now


def mark_settling(conn: Any, run_id: str) -> None:
    """Record, once and durably, that this run is settling its members."""
    conn.execute(
        "UPDATE deployment_runs SET settling_at=COALESCE(settling_at, %s) "
        "WHERE id=%s AND status='executing'",
        (iso8601_now(), run_id),
    )
    conn.commit()


def settle_members(conn: Any, run_id: str) -> Optional[str]:
    """Close every cleared member; name each that refused, or ``None``.

    Call after :func:`mark_settling`. A refusal leaves the run settling for
    a re-drive; the members that did close stay done.
    """
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        cleared_release_waits,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        close_out_satisfied_delivery_member,
    )

    refused: list[str] = []
    for member in cleared_release_waits(conn, run_id):
        outcome = close_out_satisfied_delivery_member(
            conn,
            item_id=int(member["item_id"]),
            public_ref=str(member["public_ref"]),
            run_id=run_id,
            continue_run=False,
        )
        if outcome.applies and not outcome.ok:
            refused.append(f"{member['public_ref']}: {outcome.detail}")
    if not refused:
        return None
    return (
        f"Error: cannot set status=succeeded -- run {run_id} is settling and "
        f"{len(refused)} member close-out(s) refused: {'; '.join(refused)}. "
        "A run reads succeeded only after every cleared member closes, so it "
        "stays executing and settling; members that closed stay done, and "
        "every other member keeps its claim and lane. Repair each named "
        "member, then re-drive under the project deploy lock with `yoke "
        f"deployment-runs update {run_id} status succeeded`, which replays "
        "settlement from here."
    )


__all__ = ["mark_settling", "settle_members"]
