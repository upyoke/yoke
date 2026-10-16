"""Why a settling run may not read succeeded yet, named member by member.

Every refusal leads with :data:`SETTLEMENT_BLOCKED_CODE`, so the handlers
can return it as its own error code and the deploy driver can tell a
member that must be repaired apart from a connection it may retry.
"""

from __future__ import annotations

from typing import Any

#: Error code of a ``status=succeeded`` write refused because a member the
#: run must close has not settled. Repeating the write changes nothing.
SETTLEMENT_BLOCKED_CODE = "run_settlement_blocked"

#: Why a member that could itself close is still open. Reported instead of a
#: blocker of its own, so nobody repairs a member that has nothing wrong.
HELD_WITH_RUN = (
    "it could close, and is held only because a sibling member could not; "
    "a shared gate closes every member or none"
)


def unsettled_reason(conn: Any, run_id: str, member: dict[str, Any]) -> str:
    """Why a member this run must close is still at its release wait."""
    return member_readiness_reason(conn, run_id, member) or (
        "its close-out has not completed; read `yoke items get "
        f"{member['public_ref']} status` and its done gates"
    )


def member_readiness_reason(
    conn: Any, run_id: str, member: dict[str, Any], *, blocking=None
) -> str:
    """Read settlement's delivery/QA prerequisites; never prepare or close."""
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        delivery_now_discharged,
    )
    from yoke_core.domain.deployment_qa_source_obligation import (
        unsatisfied_blocking,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )
    from yoke_core.domain.qa_done_gate_refusal import done_gate_refusal_errors

    item_id = int(member["item_id"])
    if not delivery_now_discharged(conn, item_id):
        return (
            "its delivery fact does not read delivered by this run; read "
            f"`yoke deployment-runs get {run_id}` and repair the run's "
            "completion authority for it"
        )
    if blocking is None:
        blocking = unsatisfied_blocking(conn, item_id=item_id, target_status="done")
    if blocking.count:
        # The header line restates the done refusal; each later line names
        # one open requirement and what clears it.
        lines = done_gate_refusal_errors(
            conn, blocking.rows, name=str(member["public_ref"])
        )[3:]
        return (
            f"its done gate still has {blocking.count} blocking QA "
            f"requirement(s) open: {' '.join(line.strip() for line in lines)}"
        )
    if not satisfied_delivery_member(conn, item_id=item_id, run_id=run_id):
        return (
            "its post-deploy obligations on this run are not all answered; "
            "pass or waive each one, or record `yoke qa post-deploy "
            "record-no-obligation` when nothing is observable once deployed"
        )
    return ""


def settle_refusal(run_id: str, unsettled: list[str], *, closed: bool) -> str:
    """The refusal that keeps *run_id* settling, naming every blocker."""
    if closed:
        held = (
            "every member is already closed and stays closed; only its "
            "post-close effects are outstanding"
        )
    else:
        held = (
            "none is closed: the run stays executing and settling and every "
            "member keeps its claim and lane"
        )
    return (
        f"Error: {SETTLEMENT_BLOCKED_CODE}: cannot set status=succeeded -- run "
        f"{run_id} is settling and {len(unsettled)} member(s) it must close "
        f"have not settled: {'; '.join(unsettled)}. A shared gate passes for "
        f"the run, not for one member at a time, so {held}. Repeating the "
        "write changes nothing: repair each named member; settlement replays "
        "on its own once the last blocker clears. If the run stays executing, "
        f"re-drive it with `yoke deployment-runs update {run_id} status "
        "succeeded`."
    )


__all__ = [
    "HELD_WITH_RUN",
    "SETTLEMENT_BLOCKED_CODE",
    "settle_refusal",
    "unsettled_reason",
]
