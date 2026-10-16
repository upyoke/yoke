"""Tell a released member's owner that this run cancelled its QA."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.db_optional_queries import rollback_savepoint
from yoke_core.domain.deployment_member_candidate_release import (
    CORRECTION_RELEASE_REMOVED_BY,
)
from yoke_core.domain.deployment_qa_case_failure_kinds import RED_VERDICTS
from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.deployment_run_member_removal import SETTLEMENT_REMOVED_BY
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.deployment_run_target_takeover import TAKEOVER_REMOVED_BY
from yoke_core.domain.qa_latest_execution import latest_executions

_SEND_SAVEPOINT = "_yoke_removed_member_notice"
#: A fixable failure re-lands before the owner waits on delivery; parking
#: right after a rework commit would leave the fix unlanded.
_REWORK = (
    "for a fixable failure, rework, then re-land through `yoke merge item`; "
    "park only after landing. For an external failure, record its blocker. "
    "Keep the work claim either way and park with "
)
#: Removals whose member QA continues elsewhere or whose newer candidate
#: already moved past this run: a red verdict here owes no new rework.
_NO_REWORK_SOURCES = frozenset(
    {TAKEOVER_REMOVED_BY, CORRECTION_RELEASE_REMOVED_BY, SETTLEMENT_REMOVED_BY}
)


def red_requirement_ids(conn: Any, requirement_ids: Iterable[int]) -> tuple[int, ...]:
    """Cancelled requirements whose latest attempt failed or errored."""
    latest = latest_executions(conn, requirement_ids)
    return tuple(
        sorted(
            requirement_id
            for requirement_id, row in latest.items()
            if str(row.get("verdict") or "") in RED_VERDICTS
        )
    )


def removal_notice_body(
    *,
    run_id: str,
    public_ref: str,
    reason: str,
    removed_by: str,
    red: tuple[int, ...] | None,
) -> str:
    """Pick the owner's next step; ``red=None`` means the verdict read failed.

    Removal cancels the run's QA but never classifies a failure, so a red
    verdict keeps the failure handoff's rework-or-blocker instruction.
    """
    lead = (
        f"{public_ref} was removed from run {run_id} by {removed_by}: {reason}. "
        "The outstanding run-bound QA was cancelled (not passed). "
    )
    park = (
        f"`yoke sessions touch --mode parked --reason 'awaiting {public_ref} delivery'`"
    )
    if removed_by == TAKEOVER_REMOVED_BY:
        return (
            lead + "The member's QA continues on the new run. "
            "Keep the work claim and stay parked."
        )
    if red is None:
        return (
            lead + "Its cancelled verdicts could not be read; inspect "
            f"`yoke qa requirement list --deployment-run-id {run_id}` before parking. "
            "A failed requirement still needs classification: " + _REWORK + park + "."
        )
    if red:
        failed = ", ".join(f"#{value}" for value in red)
        return (
            lead + f"Its failed item QA requirement(s) {failed} still need "
            "classification; recovery: `yoke qa plan run --help`. Classify the "
            "failure: " + _REWORK + park + ". Do not attempt close-out from this run."
        )
    return (
        lead + "The item rides a later release; do not attempt close-out or re-run "
        "merge close-out because this run succeeds. Keep the work claim and "
        f"re-park with {park}."
    )


def notify_removed_member(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    public_ref: str,
    reason: str,
    removed_by: str,
    execution_aborted: bool = False,
    cancelled_requirement_ids: Iterable[int] = (),
) -> None:
    """Queue a notice with the removal, without risking its durable write.

    A takeover that aborted no running execution sends nothing: the new run's
    item-QA wake already names that run. A takeover that stopped a running
    execution still wakes the owner, and says QA continues on the new run.
    A red verdict among the cancelled requirements keeps the rework
    instruction unless the removal source already carries the member past
    this run. The caller commits. A send failure rolls back only this
    savepoint and names the manual recovery; it never reverses removal or
    grants a pass.
    """
    takeover = removed_by == TAKEOVER_REMOVED_BY
    if takeover and not execution_aborted:
        return
    red: tuple[int, ...] | None = None
    if removed_by in _NO_REWORK_SOURCES:
        red = ()
    body = ""
    try:
        conn.execute(f"SAVEPOINT {_SEND_SAVEPOINT}")
        if red is None:
            red = red_requirement_ids(conn, cancelled_requirement_ids)
        body = removal_notice_body(
            run_id=run_id,
            public_ref=public_ref,
            reason=reason,
            removed_by=removed_by,
            red=red,
        )
        project = query_one(
            conn, "SELECT project_id FROM items WHERE id=%s", (item_id,)
        )
        removal = next(
            entry
            for entry in membership_removals(conn, run_id)
            if int(entry["item_id"]) == int(item_id)
        )
        delivery = push_member_notice(
            conn,
            item_id=item_id,
            project_id=int(project["project_id"]),
            body_for_route=lambda _route: body,
            idempotency_key=f"removed-member:{run_id}:{item_id}:{removal['removed_at']}",
        )
    except Exception as exc:  # noqa: BLE001 - removal survives a notice failure
        rollback_savepoint(conn, _SEND_SAVEPOINT)
        body = body or removal_notice_body(
            run_id=run_id,
            public_ref=public_ref,
            reason=reason,
            removed_by=removed_by,
            red=red,
        )
        print(
            f"member_removal_notice_failed: {public_ref} on {run_id}: {exc}. "
            f"Notify its holder manually: {body}",
            flush=True,
        )
        return
    conn.execute(f"RELEASE SAVEPOINT {_SEND_SAVEPOINT}")
    if not delivery:
        print(
            f"member_removal_notice_unaddressable: {public_ref} on {run_id}; "
            f"no holder or steering seat is addressable. Notify its owner manually: {body}",
            flush=True,
        )
