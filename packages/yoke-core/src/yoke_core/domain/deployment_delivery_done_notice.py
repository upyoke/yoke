"""Tell an item's owner that its delivery completed, once, informationally.

A released item's owner learns the outcome from the notice this sends:
what was delivered, where it went, and the run whose evidence backs it.
It is informational by construction — no decision, nothing to
acknowledge, and no gate anywhere reads it. Failing to deliver it never
reverses a done that already happened; the caller reports the failure and
the notice stays retryable.

Only an item whose delivery actually ran gets one. A merge-only item has
no destination to name, and a progress-delivery member does not reach
done from the run that carried it, so "once at final completion" needs no
separate guard: done happens once, and the notice is keyed to the item
and the run that delivered it.

Recipient is the same rule every item-addressed notice uses — the item's
claim holder, or the project's steering seat when the holder is gone —
because the owning agent is who holds the claim at completion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice


def delivery_done_idempotency_key(item_id: int, run_id: str) -> str:
    """One notice per item and the run that delivered it."""
    return f"delivery-done:{item_id}:{run_id}"


def delivery_done_message(
    *,
    item_ref: str,
    run_id: str,
    destination: str,
    revision: str,
    intent: str,
    route: str,
) -> str:
    """Name the outcome, its destination, and where the evidence lives."""
    addressed = (
        f"{item_ref}'s owner"
        if route == HOLDER
        else f"{item_ref}'s project steering seat (its owner is gone)"
    )
    rev = (revision or "")[:12] or "an unresolved revision"
    carried = "Final delivery" if intent == "final" else "Delivery"
    return (
        f"{item_ref} is done. {carried} completed to {destination} at {rev} "
        f"through deployment run {run_id}. Reaching {addressed}: this is "
        "informational — nothing to approve and nothing to acknowledge. Its "
        f"evidence is on the run: 'yoke deployment-runs get {run_id}'."
    )


def _delivered_run(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    """The item's own succeeded run, with the destination it delivered to.

    ``None`` means there is nothing to announce: no run, or none that
    succeeded. A failed or cancelled run is not a delivery, so its
    absence of a notice is the correct outcome rather than a gap.
    """
    row = conn.execute(
        "SELECT dr.id,dr.release_lineage,dr.target_tier,dr.project_id,"
        "dri.delivery_intent,"
        "COALESCE((SELECT e.name FROM environments e "
        "WHERE e.id=dr.target_environment_id),'') AS environment_name "
        "FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id=dr.id "
        "WHERE dri.item_id=%s AND dr.status='succeeded' "
        "ORDER BY dr.completed_at DESC NULLS LAST,dr.created_at DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    return {str(key): row[key] for key in row.keys()}


def notify_delivery_done(
    conn: Any, *, item_id: int, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Send one informational owner notice for a completed delivery.

    ``delivery`` follows :func:`merge_queue_landing_notice.push_notice`'s
    contract; ``reason`` explains an empty one so the caller can report
    "no delivery to announce" separately from "nobody to tell".
    """
    from yoke_core.domain.project_identity import render_item_ref

    run = _delivered_run(conn, item_id)
    if run is None:
        return {
            "delivery": "",
            "run_id": "",
            "reason": "no succeeded deployment run is attached to this item",
        }
    run_id = str(run["id"])
    destination = (
        str(run["environment_name"])
        or str(run["target_tier"] or "")
        or "an unnamed destination"
    )
    item_ref = render_item_ref(conn, int(item_id))
    delivery = push_notice(
        conn,
        item_id=int(item_id),
        project_id=int(run["project_id"]),
        body_for_route=lambda route: delivery_done_message(
            item_ref=item_ref,
            run_id=run_id,
            destination=destination,
            revision=str(run["release_lineage"] or ""),
            intent=str(run["delivery_intent"] or ""),
            route=route,
        ),
        idempotency_key=delivery_done_idempotency_key(int(item_id), run_id),
        now=now or datetime.now(timezone.utc),
    )
    return {
        "delivery": delivery,
        "run_id": run_id,
        "reason": (
            ""
            if delivery
            else "no live claim holder and no covering project steering seat"
        ),
    }


__all__ = [
    "delivery_done_idempotency_key",
    "delivery_done_message",
    "notify_delivery_done",
]
