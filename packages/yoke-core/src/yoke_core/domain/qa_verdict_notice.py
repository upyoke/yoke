"""Route resolved QA reviews to the session responsible for their subject."""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.deployment_qa_verdict_notice import notify_deployment_qa_verdict
from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice
from yoke_core.domain.project_identity import render_item_ref


def notify_qa_verdict(
    conn: Any, *, requirement_id: int, action: str, note: str = ""
) -> str:
    """Reuse deployment routing, or tell an item's holder (otherwise steering).

    Session envelopes retain undelivered notices for steering's normal view.
    An unaddressable subject returns an empty string to the decision resolver,
    which reports the missing recipient without reversing the verdict.
    """
    row = conn.execute(
        "SELECT COALESCE(q.item_id,q.epic_id) AS item_id,i.project_id,"
        "q.deployment_run_id,q.deployment_stage FROM qa_requirements q "
        "LEFT JOIN items i ON i.id=COALESCE(q.item_id,q.epic_id) WHERE q.id=%s",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return ""
    if row["deployment_run_id"] and row["deployment_stage"]:
        return notify_deployment_qa_verdict(
            conn, requirement_id=requirement_id, action=action, note=note
        )
    if row["item_id"] is None or row["project_id"] is None:
        return ""
    item_id = int(row["item_id"])
    item_ref = render_item_ref(conn, item_id)
    outcome = {"approve": "approved", "reject": "rejected", "waive": "waived"}[action]
    next_step = {
        "approve": "resume the item's pinned workflow; the reviewed evidence was accepted",
        "reject": "read the rejection and evidence, correct the failing check, and record fresh evidence",
        "waive": "the obligation is discharged; resume the item's pinned workflow",
    }[action]

    def body(route: str) -> str:
        recovery = (
            ""
            if route == HOLDER
            else " No item claim holder is available; staff the item and relay this verdict."
        )
        reviewer = f" Reviewer note: {note}" if note.strip() else ""
        return (
            f"Human verdict on QA requirement {requirement_id} for {item_ref} "
            f"was {outcome}: {next_step}.{reviewer}{recovery} "
            f"Read `yoke qa requirement get --requirement-id {requirement_id}`."
        )

    return push_notice(
        conn,
        item_id=item_id,
        project_id=int(row["project_id"]),
        body_for_route=body,
        idempotency_key=f"item-qa-verdict:{requirement_id}:{action}",
        now=parse_instant(utc_now()),
    )
