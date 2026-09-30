"""Close a delivery-cleared member whose post-deploy work is satisfied.

The merge close-out is the one path to done. This module runs that same
close-out without a session when either the member recorded
``post_deploy_no_obligation`` or its completion-flow QA requirements all
passed or were discharged. An empty case set is still a member nobody asked
and stays held.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.post_deploy_verification_answer import answer_for_item
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.schema_common import _table_exists


@dataclass(frozen=True)
class DeliveryMemberCloseOut:
    """Whether this member can close without a wake, and the result.

    ``applies`` is the predicate the wake sites read: false means this is
    not an automatic-close case, so the ordinary delivery wake fires. True
    with ``ok=False`` tells the caller to send a recovery notice carrying
    ``detail``; a failed close-out must never strand the release-wait owner.
    """

    applies: bool
    ok: bool = False
    detail: str = ""


def recorded_no_obligation(conn: Any, item_id: int) -> bool:
    """The authored no-obligation fact, not a waiver and not silence."""
    return answer_for_item(conn, int(item_id)).no_obligation


def satisfied_delivery_member(conn: Any, *, item_id: int, run_id: str) -> bool:
    """Whether this run settled every scoped QA obligation for the member."""
    if recorded_no_obligation(conn, int(item_id)):
        return True
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return False
    total = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_requirements r "
        "WHERE r.deployment_run_id=%s AND r.deployment_member_item_id=%s "
        "AND r.qa_phase='post_deploy' AND r.blocking_mode='blocking'",
        (str(run_id), int(item_id)),
    )
    if not int(total or 0):
        return False
    unresolved = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_requirements r "
        "WHERE r.deployment_run_id=%s AND r.deployment_member_item_id=%s "
        "AND r.qa_phase='post_deploy' AND r.blocking_mode='blocking' "
        f"AND NOT {settled_obligation_sql(conn, 'r')} "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs qr "
        "WHERE qr.qa_requirement_id=r.id AND qr.verdict='pass')",
        (str(run_id), int(item_id)),
    )
    return int(unresolved or 0) == 0


def close_out_satisfied_delivery_member(
    conn: Any,
    *,
    item_id: int,
    public_ref: str,
    run_id: str,
) -> DeliveryMemberCloseOut:
    """Run the merge close-out for one delivery-cleared satisfied member.

    Evidence must already be on the item from landing; this path never
    invents ``--result`` or ``--verification``. The member's prerequisites
    commit, then its terminal status and claim release commit together, then
    its effects run; a failed effect is reported and never reopens it. A
    run's own settlement stages its members into one commit instead
    (:mod:`deployment_run_collective_finalization`).
    """
    from yoke_core.domain import delivery_member_close_steps as steps
    from yoke_core.domain.project_identity import render_item_ref

    if not satisfied_delivery_member(conn, item_id=int(item_id), run_id=run_id):
        return DeliveryMemberCloseOut(applies=False)
    named = str(public_ref).strip() or render_item_ref(conn, int(item_id))
    try:
        refusal = steps.prepare_member_close(
            conn, item_id=int(item_id), public_ref=named
        )
        written = (
            None
            if refusal
            else steps.stage_member_close(conn, item_id=int(item_id), public_ref=named)
        )
    except Exception as exc:  # noqa: BLE001 - never reverse the succeeded run
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - the notice path reports its own failure
            pass
        return DeliveryMemberCloseOut(
            applies=True, ok=False, detail=str(exc) or exc.__class__.__name__
        )
    if written is not None and written.refusal:
        refusal = written.refusal
    if refusal:
        conn.rollback()
        return DeliveryMemberCloseOut(
            applies=True,
            ok=False,
            detail=(
                f"{named} has satisfied post-deploy delivery but cannot "
                f"auto-close: {refusal}"
            ),
        )
    if written is None or written.receipt is None:
        return DeliveryMemberCloseOut(applies=True, ok=True, detail="already done")
    conn.commit()
    failure = steps.run_closed_member_effects(
        conn, item_id=int(item_id), public_ref=named, receipt=written.receipt
    )
    if failure:
        print(
            f"{named} closed, but its post-close effects did not finish: "
            f"{failure}. The item stays done; any lane it left active shows "
            f"in `yoke item-worktrees list {named}`."
        )
    from yoke_core.domain.deployment_run_auto_completion import (
        continue_after_settlement,
    )

    try:
        continue_after_settlement(conn, run_id)
    except Exception as exc:  # noqa: BLE001 - the member is closed either way
        conn.rollback()
        print(
            f"{named} closed, but run {run_id} could not continue: {exc}. "
            "Re-drive it under the project deploy lock with "
            f"`yoke deployment-runs update {run_id} status succeeded`."
        )
    return DeliveryMemberCloseOut(applies=True, ok=True, detail="closed")


__all__ = [
    "DeliveryMemberCloseOut",
    "close_out_satisfied_delivery_member",
    "recorded_no_obligation",
    "satisfied_delivery_member",
]
