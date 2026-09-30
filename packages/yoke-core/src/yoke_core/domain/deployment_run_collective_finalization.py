"""A run reads succeeded only after every cleared member has closed.

A run whose shared gates passed used to commit ``succeeded`` and close its
members afterwards, so any refusal, failed write, or interrupted process in
between left a green run over members still at their release wait.

Settlement reverses that order through one durable, non-terminal state. The
run stays ``executing`` and records ``settling_at``; completion authority
reads a settling run as delivered, so each member's own done gates can pass.

Closing is then all-or-nothing. A shared gate passes for the run, not for one
member at a time, so every cleared member is asked whether it *could* close
before any of them does. If even one cannot, none is closed and the refusal
names each blocker: a run whose members half-closed is a worse state to
recover from than one that did not start, because the members that closed
have already released their claims and lanes.

Anything that stops settlement after that check leaves the run ``executing``
and settling with its members' own states intact. Re-driving ``status
succeeded`` replays settlement from there — a member already done is no longer
at its wait, so nothing is closed twice.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now


#: Why a member that could itself close is still open. Reported instead of a
#: blocker of its own, so nobody repairs a member that has nothing wrong.
HELD_WITH_RUN = (
    "it could close, and is held only because a sibling member could not; "
    "a shared gate closes every member or none"
)


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


def _blocked_members(
    conn: Any, run_id: str, members: list[dict[str, Any]]
) -> dict[int, str]:
    """Name every cleared member that could not close, closing none of them.

    Residue is cleared first: an item-level execution that recorded nothing
    is superseded here, because the walk that would abort it is the one that
    already finished as this run's own scoped item QA. Only then is each
    member asked whether its close-out would pass.
    """
    from yoke_core.domain.deployment_member_close_readiness import (
        member_close_blocker,
    )
    from yoke_core.domain.qa_resultless_execution_supersession import (
        supersede_resultless_item_executions,
    )

    blocked: dict[int, str] = {}
    for member in members:
        item_id = int(member["item_id"])
        public_ref = str(member["public_ref"])
        unresolved = supersede_resultless_item_executions(
            conn, item_id=item_id, run_id=run_id, public_ref=public_ref
        )
        if unresolved:
            blocked[item_id] = "; ".join(unresolved)
            continue
        if blocker := member_close_blocker(
            conn, item_id=item_id, public_ref=public_ref
        ):
            blocked[item_id] = blocker
    return blocked


def settle_members(conn: Any, run_id: str) -> Optional[str]:
    """Close every cleared member together, or none of them.

    Call after :func:`mark_settling`. A required member is one this run is
    the final delivery of and has completion authority for; while any is
    still at its release wait — its close-out would refuse, or it was never
    cleared — the run may not succeed and no member closes.
    """
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        cleared_release_waits,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        close_out_satisfied_delivery_member,
    )

    cleared = cleared_release_waits(conn, run_id)
    refusals = _blocked_members(conn, run_id, cleared)
    held_with_run = bool(refusals)
    if not held_with_run:
        for member in cleared:
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
            or (HELD_WITH_RUN if held_with_run else "")
            or _unsettled_reason(conn, run_id, member["item_id"])
        )
        for member in _required_open_members(conn, run_id)
    ]
    if not unsettled:
        return None
    return (
        f"Error: cannot set status=succeeded -- run {run_id} is settling and "
        f"{len(unsettled)} member(s) it must close remain at their release "
        f"wait: {'; '.join(unsettled)}. A shared gate passes for the run, not "
        "for one member at a time, so while any named member cannot close, "
        "none is closed: the run stays executing and settling and every "
        "member keeps its claim and lane. Repair each named member; "
        "settlement replays on its own once the last blocker clears. If the "
        "run stays executing, re-drive it under the project deploy lock with "
        f"`yoke deployment-runs update {run_id} status succeeded`."
    )


__all__ = ["HELD_WITH_RUN", "mark_settling", "settle_members"]
