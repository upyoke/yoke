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


def _unsettled_reason(conn: Any, run_id: str, item_id: int) -> str:
    """Why a member this run must close is still at its release wait."""
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        delivery_now_discharged,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

    if not delivery_now_discharged(conn, item_id):
        return (
            "its delivery fact does not read delivered by this run; read "
            f"`yoke deployment-runs get {run_id}` and repair the run's "
            "completion authority for it"
        )
    if not satisfied_delivery_member(conn, item_id=item_id, run_id=run_id):
        return (
            "its post-deploy obligations on this run are not all answered; "
            "pass or waive each one, or record `yoke qa post-deploy "
            "record-no-obligation` when nothing is observable once deployed"
        )
    return "its close-out has not completed"


def _required_open_members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Members this run is the final delivery of, still at their wait."""
    from yoke_core.domain.deployment_delivery_close_out_notice import run_members
    from yoke_core.domain.deployment_member_run_coverage import member_run_coverage
    from yoke_core.domain.deployment_run_composition_freeze import (
        DELIVERY_INTENT_PROGRESS,
    )
    from yoke_core.domain.release_wait_ownership import item_at_release_wait
    from yoke_contracts.public_ref import format_item_ref

    open_members: list[dict[str, Any]] = []
    for row in run_members(conn, run_id):
        if row["delivery_intent"] == DELIVERY_INTENT_PROGRESS:
            continue
        if not item_at_release_wait(row, str(row["status"] or "")):
            continue
        item_id = int(row["item_id"])
        if not member_run_coverage(conn, run_id=run_id, item_id=item_id).closes:
            continue
        open_members.append(
            {
                "item_id": item_id,
                "public_ref": format_item_ref(
                    None, row["public_item_prefix"], row["project_sequence"]
                ),
            }
        )
    return open_members


def settle_members(conn: Any, run_id: str) -> Optional[str]:
    """Close every cleared member; name each required member still open.

    Call after :func:`mark_settling`. A required member is one this run is
    the final delivery of and has completion authority for; while any is
    still at its release wait — its close-out refused, or it was never
    cleared — the run may not succeed. Members that did close stay done.
    """
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        cleared_release_waits,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        close_out_satisfied_delivery_member,
    )

    refusals: dict[int, str] = {}
    for member in cleared_release_waits(conn, run_id):
        outcome = close_out_satisfied_delivery_member(
            conn,
            item_id=int(member["item_id"]),
            public_ref=str(member["public_ref"]),
            run_id=run_id,
            continue_run=False,
        )
        if outcome.applies and not outcome.ok:
            refusals[int(member["item_id"])] = outcome.detail
    unsettled = [
        f"{member['public_ref']}: "
        + (
            refusals.get(member["item_id"])
            or _unsettled_reason(conn, run_id, member["item_id"])
        )
        for member in _required_open_members(conn, run_id)
    ]
    if not unsettled:
        return None
    return (
        f"Error: cannot set status=succeeded -- run {run_id} is settling and "
        f"{len(unsettled)} member(s) it must close remain at their release "
        f"wait: {'; '.join(unsettled)}. A run reads succeeded only after every "
        "member it finally delivers has closed, so it stays executing and "
        "settling; members that closed stay done, and every other member "
        "keeps its claim and lane. Repair each named member, then re-drive "
        f"under the project deploy lock with `yoke deployment-runs update "
        f"{run_id} status succeeded`, which replays settlement from here."
    )


__all__ = ["mark_settling", "settle_members"]
