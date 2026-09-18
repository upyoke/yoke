"""Wake the release-wait owner whose own delivery obligation just cleared.

An item that merged into a pinned release wait is held by the session that
merged it, parked on that wait. Something has to tell that session the wait
is over, and until now nothing did: the QA-stage wake reaches a holder a
stage is WAITING on, the verdict notice reaches one whose review was
decided, and the delivery-done notice reaches the item's human owner AFTER
done. A run that simply succeeded — the ordinary case, and the whole case
for an item with no human-gated stage — told the one session that could
finish the close-out nothing at all.

Two rules keep this notice from causing the loss it exists to prevent.

**It fires only for a member whose release obligation this run discharged.**
Not every succeeded run that carries an item makes that item's ``done``
possible: a stage-then-production pair succeeds twice, and only the run on
the item's own completion flow is the one the done gate counts. Telling a
holder otherwise is worse than silence — the prompt that delivers it clears
the park, the close-out it prompts is refused because delivery has not
cleared, and the owner is left unparked and reclaimable, which is exactly
the abandonment this whole item prevents. So the test is the gate's own
:data:`gate_satisfier_item_facts.ITEM_DEPLOYMENT_RUN_SUCCEEDED` fact rather
than the run's success, its tier, or its intent: if that fact does not say
done is now possible, this run is not the one to announce.

**Each send is isolated and never reverses the delivery.** It runs after the
run's status is committed, and every send takes its own savepoint, so a
failed insert cannot abort the transaction its siblings need — on Postgres a
single failed statement poisons the whole transaction, which would have
turned one undeliverable notice into a lost ``succeeded`` write.

The recipient is :func:`merge_queue_landing_notice.resolve_lane_recipient`'s,
so the item's claim holder answers first and the project's steering seat
answers for a lane nobody holds. No new scheduler, table, or service — one
notice per item and the run that delivered it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.db_optional_queries import rollback_savepoint
from yoke_core.domain.gate_satisfier_facts import FactVerdict
from yoke_core.domain.gate_satisfier_item_facts import (
    ITEM_DEPLOYMENT_RUN_SUCCEEDED,
    load_item_facts,
)
from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice
from yoke_core.domain.release_wait_ownership import item_at_release_wait
from yoke_core.domain.schema_common import _table_exists
from yoke_contracts.public_ref import format_item_ref

#: One notice per item and the run whose delivery cleared it.
DELIVERY_CLEARED_KEY_PREFIX = "release-wait-delivery-cleared:"

_SEND_SAVEPOINT = "_yoke_delivery_cleared_notice"


def delivery_cleared_idempotency_key(item_id: int, run_id: str) -> str:
    """One notice per item and the run that cleared its wait."""
    return f"{DELIVERY_CLEARED_KEY_PREFIX}{item_id}:{run_id}"


def delivery_cleared_message(
    *, public_ref: str, run_id: str, route: str
) -> str:
    """Name what cleared, and the exact command that finishes the item."""
    lead = (
        f"{public_ref}'s delivery cleared: deployment run {run_id} succeeded "
        f"and the item is still at its release wait."
    )
    if route == HOLDER:
        return (
            f"{lead} You hold its work claim and parked on this wait, so this "
            f"is your re-entry: walk any post-deploy validation the run owes, "
            f"then re-run `yoke merge item {public_ref} --result ... "
            f"--verification ...` to record the evidence and close the item "
            f"out. Report and end only once it reaches done. If anything "
            f"leaves it short of done, re-park before going quiet — this "
            f"prompt cleared your previous park."
        )
    return (
        f"{lead} Nobody holds its work claim, so no worker will close it out: "
        f"staff a session at `/yoke dash {public_ref}`, or close it out "
        f"directly with `yoke merge item {public_ref} --result ... "
        f"--verification ...`. Its evidence is on the run: "
        f"`yoke deployment-runs get {run_id}`."
    )


def _run_members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Every item this run carries, with the facts the wait test needs."""
    required = ("deployment_run_items", "items", "projects", "workflow_versions")
    if not all(_table_exists(conn, name) for name in required):
        return []
    return list(
        conn.execute(
            "SELECT i.id AS item_id,i.project_id,i.status,i.project_sequence,"
            "i.workflow_id,i.workflow_version_id,p.public_item_prefix,"
            "v.version,v.definition_json,v.definition_digest "
            "FROM deployment_run_items dri "
            "JOIN items i ON i.id=dri.item_id "
            "JOIN projects p ON p.id=i.project_id "
            "JOIN workflow_versions v ON v.id=i.workflow_version_id "
            "WHERE dri.run_id=%s ORDER BY i.id",
            (run_id,),
        ).fetchall()
    )


def _delivery_now_discharged(conn: Any, item_id: int) -> bool:
    """Whether the done gate's own delivery fact now reads satisfied.

    Asking the gate rather than re-deriving it is the point: the fact keys
    off the item's completion flow, so a sibling run on another flow — the
    stage half of a stage-then-production pair — correctly answers no. An
    unreadable fact answers no too, because announcing a clearance this
    could not confirm is what unparks an owner that still has to wait.
    """
    try:
        fact = load_item_facts(conn, int(item_id)).get(
            ITEM_DEPLOYMENT_RUN_SUCCEEDED
        )
    except Exception:  # noqa: BLE001 - an unreadable fact announces nothing
        return False
    return fact is not None and fact.verdict == FactVerdict.PRESENT


def _cleared_release_waits(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Members standing at a release wait this run's success discharged."""
    cleared: list[dict[str, Any]] = []
    for row in _run_members(conn, run_id):
        if not item_at_release_wait(row, str(row["status"] or "")):
            continue
        item_id = int(row["item_id"])
        if not _delivery_now_discharged(conn, item_id):
            continue
        cleared.append(
            {
                "item_id": item_id,
                "project_id": int(row["project_id"]),
                "public_ref": format_item_ref(
                    None, row["public_item_prefix"], row["project_sequence"]
                ),
            }
        )
    return cleared


def _send(conn: Any, member: dict[str, Any], run_id: str, stamp: datetime) -> str:
    """Send one member's notice inside its own savepoint.

    The savepoint is the isolation this needs: without it a single failed
    insert aborts the caller's transaction, taking every sibling notice —
    and on the pre-commit shape, the run's own ``succeeded`` write — with it.
    """
    public_ref = str(member["public_ref"])
    try:
        conn.execute(f"SAVEPOINT {_SEND_SAVEPOINT}")
    except Exception as exc:  # noqa: BLE001 - reported, never reverses delivery
        return f"failed: {exc}"
    try:
        delivery = push_notice(
            conn,
            item_id=int(member["item_id"]),
            project_id=int(member["project_id"]),
            body_for_route=lambda route, ref=public_ref: (
                delivery_cleared_message(public_ref=ref, run_id=run_id, route=route)
            ),
            idempotency_key=delivery_cleared_idempotency_key(
                int(member["item_id"]), run_id
            ),
            now=stamp,
        )
    except Exception as exc:  # noqa: BLE001 - reported, never reverses delivery
        rollback_savepoint(conn, _SEND_SAVEPOINT)
        return f"failed: {exc}"
    try:
        conn.execute(f"RELEASE SAVEPOINT {_SEND_SAVEPOINT}")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - reported, never reverses delivery
        return f"failed: {exc}"
    return delivery


def notify_delivery_cleared(
    conn: Any, *, run_id: str, now: Optional[datetime] = None
) -> list[dict[str, Any]]:
    """Tell every owner whose wait this run cleared, one isolated send each.

    Returns one record per announced member with what delivery did, so a
    caller can report a notice that did not land without treating it as a
    run failure. Call it only after the run's own status is committed.
    """
    stamp = now or datetime.now(timezone.utc)
    return [
        {
            "public_ref": member["public_ref"],
            "delivery": _send(conn, member, run_id, stamp),
        }
        for member in _cleared_release_waits(conn, run_id)
    ]


__all__ = [
    "DELIVERY_CLEARED_KEY_PREFIX",
    "delivery_cleared_idempotency_key",
    "delivery_cleared_message",
    "notify_delivery_cleared",
]
