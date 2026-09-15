"""Tell an item's owner that its delivery completed, once, informationally.

The recipient is the item's OWNER — the human member ``items.owner``
names — reached through the actor-addressed Fleet path, which is the
Inbox surface a person reads. It is deliberately not the session holding
the item's work claim: that is an agent, the agent already gets woken for
QA stages it owes work on, and an owner notice that quietly redirects to
whichever agent happens to hold the claim tells the wrong party and
looks like it worked. An item whose owner does not resolve to a human
member reports that, and nothing is sent.

It is informational by construction — no decision, nothing to
acknowledge, and no gate anywhere reads it. Failing to deliver it never
reverses a done that already happened; the caller reports the failure and
the notice stays retryable. The QA-result notice is a separate event with
its own key, so an owner who is also a reviewer legitimately receives
both.

Only an item whose delivery actually ran gets one, and the destination it
names is the one the run was observed to deliver to — its stage
receipts' own ``target_name`` — rather than whatever environment the run
was configured to aim at. A merge-only item has no destination at all,
and a progress-delivery member does not reach done from the run that
carried it, so "once at final completion" needs no separate guard: done
happens once, and the key is the item plus the run that delivered it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.actors import is_human_actor
from yoke_core.domain.session_message_service import send_message


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
) -> str:
    """Name the outcome, its destination, and where the evidence lives."""
    rev = (revision or "")[:12] or "an unresolved revision"
    carried = "Final delivery" if intent == "final" else "Delivery"
    return (
        f"{item_ref} is done. {carried} completed to {destination} at {rev} "
        f"through deployment run {run_id}. This is informational — nothing to "
        "approve and nothing to acknowledge. Its evidence is on the run: "
        f"'yoke deployment-runs get {run_id}'."
    )


def _owner_actor(conn: Any, item_id: int) -> Optional[int]:
    """The human member this item belongs to, or ``None``.

    ``items.owner`` holds a stringified ``actors.id`` on every row the
    current write path produced, and a legacy free-text token on older
    ones. A token that is not a human actor id is not an owner this can
    address, and saying so beats redirecting the notice at an agent.
    """
    row = conn.execute("SELECT owner FROM items WHERE id=%s", (int(item_id),)).fetchone()
    if row is None:
        return None
    raw = str(row["owner"] or "").strip()
    if not raw.isdigit():
        return None
    actor_id = int(raw)
    return actor_id if is_human_actor(conn, actor_id) else None


def _delivered_run(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    """The item's own succeeded run, with the destination it delivered to.

    ``None`` means there is nothing to announce: no run, or none that
    succeeded. A failed or cancelled run is not a delivery, so its
    absence of a notice is the correct outcome rather than a gap.

    The destination prefers the newest ready stage receipt's observed
    target over the run's configured ``target_environment``, because a
    journey with more than one environment stage is configured to aim at
    one of them and observed to reach each; the configured value answers
    only when nothing observed one.
    """
    row = conn.execute(
        "SELECT dr.id,dr.release_lineage,dr.target_tier,dr.project_id,"
        "dri.delivery_intent,"
        "COALESCE((SELECT e.name FROM environments e "
        "WHERE e.id=dr.target_environment_id),'') AS configured_environment,"
        "COALESCE((SELECT r.target_name FROM deployment_stage_receipts r "
        "WHERE r.run_id=dr.id AND r.status='ready' "
        "AND TRIM(COALESCE(r.target_name,'')) <> '' "
        "ORDER BY r.completed_at DESC,r.id DESC LIMIT 1),'') AS observed_target "
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

    ``delivery`` is ``"notified"`` when the owner's Inbox row was written
    and ``""`` when nothing was sent; ``reason`` explains an empty one so
    the caller can report "no delivery to announce" separately from "no
    owner to tell".
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
    owner_actor_id = _owner_actor(conn, item_id)
    if owner_actor_id is None:
        return {
            "delivery": "",
            "run_id": run_id,
            "reason": (
                "items.owner names no human organization member to notify; "
                "set the item's owner to an actor id"
            ),
        }
    destination = (
        str(run["observed_target"])
        or str(run["configured_environment"])
        or str(run["target_tier"] or "")
        or "an unnamed destination"
    )
    created = send_message(
        conn,
        actor_id=owner_actor_id,
        sender_session_id=None,
        selector=RecipientSelector(actors=[str(owner_actor_id)]),
        body=delivery_done_message(
            item_ref=render_item_ref(conn, int(item_id)),
            run_id=run_id,
            destination=destination,
            revision=str(run["release_lineage"] or ""),
            intent=str(run["delivery_intent"] or ""),
        ),
        idempotency_key=delivery_done_idempotency_key(int(item_id), run_id),
        idempotency_intent_only=True,
        now=now or datetime.now(timezone.utc),
        commit=False,
    )
    return {
        "delivery": "notified",
        "run_id": run_id,
        "message_id": str(created["message_id"]),
        "owner_actor_id": owner_actor_id,
        "reason": "",
    }


__all__ = [
    "delivery_done_idempotency_key",
    "delivery_done_message",
    "notify_delivery_done",
]
