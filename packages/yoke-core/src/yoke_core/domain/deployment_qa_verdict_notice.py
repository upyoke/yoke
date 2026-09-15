"""Tell the agent that parked for a human QA verdict what the answer was.

A deployment stage whose verdict policy requires a human opens a review
request and the stage waits. The agent that supplied the evidence parks,
because there is nothing for it to do until somebody decides. The
decision landing in the control plane is not by itself an answer that
reaches it: without this, an approved stage sits until something else
happens to wake that session, and a rejection — the case where the agent
has real work to do — is the quietest of all.

Recipient is the same one the wait itself addressed, so a verdict lands
where the question did: an item-scoped stage reaches that member's claim
holder (or the project's steering seat when the holder is gone), a
run-scoped stage reaches the project's deploy-lock driver. A requirement
that is not a deployment-stage subject is not this module's business and
reports no recipient rather than guessing at one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice
from yoke_core.domain.deployment_qa_stage_wake import (
    DRIVER,
    push_run_scoped_notice,
)


#: Verdict notices are keyed by the decided requirement and its outcome, so
#: a retried delivery of the same decision is one notice while a later,
#: different decision on the same requirement is its own.
def verdict_idempotency_key(requirement_id: int, action: str) -> str:
    """One notice per decided requirement and outcome."""
    return f"deployment-qa-stage-verdict:{requirement_id}:{action}"


def verdict_message(
    *,
    run_id: str,
    stage_name: str,
    subject: str,
    action: str,
    note: str,
    route: str,
) -> str:
    """Name the decision, what it was about, and what to do next.

    The next step differs by outcome and is the reason this notice exists
    at all: an approval releases a parked agent to carry on, a rejection
    hands it concrete work, and a waiver tells it the obligation was
    discharged without its evidence.
    """
    outcome = {
        "approve": "was approved",
        "reject": "was rejected",
        "waive": "was waived",
    }.get(action, f"was resolved as {action!r}")
    next_step = {
        "approve": "the stage can advance; resume the run",
        "reject": (
            "address the rejection on this stage's target and record fresh "
            "evidence before the stage can advance"
        ),
        "waive": "the obligation is discharged; no further evidence is needed",
    }.get(action, "read the decision and continue")
    addressed = (
        "you"
        if route in {HOLDER, DRIVER}
        else "the project's steering seat (the agent that supplied the "
        "evidence is gone)"
    )
    reason = f" Reviewer note: {note}" if note.strip() else ""
    return (
        f"Human verdict on deployment run {run_id} stage {stage_name!r} "
        f"({subject}) {outcome}. Reaching {addressed}: {next_step}.{reason} "
        f"Check 'yoke deployment-runs get {run_id}' for the current state."
    )


def _deployment_subject(conn: Any, requirement_id: int) -> Optional[dict[str, Any]]:
    """The run/stage/member this requirement belongs to, or ``None``.

    ``None`` covers every QA requirement that is not a deployment-stage
    subject — an ordinary item or plan requirement — which this module has
    no business notifying about.
    """
    row = conn.execute(
        "SELECT q.deployment_run_id,q.deployment_stage,"
        "q.deployment_member_item_id,r.project_id "
        "FROM qa_requirements q "
        "LEFT JOIN deployment_runs r ON r.id=q.deployment_run_id "
        "WHERE q.id=%s",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return None
    run_id = str(row["deployment_run_id"] or "").strip()
    stage_name = str(row["deployment_stage"] or "").strip()
    if not run_id or not stage_name or row["project_id"] is None:
        return None
    member = row["deployment_member_item_id"]
    return {
        "run_id": run_id,
        "stage_name": stage_name,
        "member_item_id": int(member) if member is not None else None,
        "project_id": int(row["project_id"]),
    }


def notify_deployment_qa_verdict(
    conn: Any,
    *,
    requirement_id: int,
    action: str,
    note: str = "",
    now: Optional[datetime] = None,
) -> str:
    """Reach the agent a resolved deployment-stage review was waiting on.

    Returns :func:`merge_queue_landing_notice.push_notice`'s contract —
    ``""`` nobody addressable (including "this is not a deployment-stage
    requirement"), ``"undelivered"`` queued, ``"delivered"`` reached.
    """
    subject = _deployment_subject(conn, requirement_id)
    if subject is None:
        return ""
    run_id = subject["run_id"]
    stage_name = subject["stage_name"]
    member_item_id = subject["member_item_id"]
    key = verdict_idempotency_key(requirement_id, action)
    if member_item_id is None:
        return push_run_scoped_notice(
            conn,
            project_id=subject["project_id"],
            body_for_route=lambda route: verdict_message(
                run_id=run_id,
                stage_name=stage_name,
                subject="the whole release batch",
                action=action,
                note=note,
                route=route,
            ),
            idempotency_key=key,
            now=now,
        )
    from yoke_core.domain.project_identity import render_item_ref

    item_ref = render_item_ref(conn, member_item_id)
    return push_notice(
        conn,
        item_id=member_item_id,
        project_id=subject["project_id"],
        body_for_route=lambda route: verdict_message(
            run_id=run_id,
            stage_name=stage_name,
            subject=item_ref,
            action=action,
            note=note,
            route=route,
        ),
        idempotency_key=key,
        now=now or datetime.now(timezone.utc),
    )


__all__ = [
    "notify_deployment_qa_verdict",
    "verdict_idempotency_key",
    "verdict_message",
]
