"""Wake the release-wait owner whose delivery just cleared.

An item that merged into a pinned release wait is held by the session that
merged it, parked on that wait. Something has to tell that session the wait
is over, and until now nothing did: the QA-stage wake reaches a holder a
stage is WAITING on, the verdict notice reaches one whose review was
decided, and the delivery-done notice reaches the item's human owner AFTER
done. A run that simply succeeded — the ordinary case, and the whole case
for an item with no human-gated stage — told the one session that could
finish the close-out nothing at all, so the item sat at its release wait
with an owner who had no reason to wake.

This is that missing edge, and deliberately the same edge as the rest: the
recipient is :func:`merge_queue_landing_notice.resolve_lane_recipient`'s, so
the item's claim holder answers first and the project's steering seat
answers for a lane nobody holds. No new scheduler, table, or service — one
notice per item and the run that delivered it.

Only a member still standing at its pinned release wait is told. A member
already at done needs nothing, and one that never reached the wait is not
this run's business. A delivery failure here never reverses the run: the
deploy happened, and the notice stays keyed so a later attempt is the same
notice rather than a second one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row
from yoke_contracts.public_ref import format_item_ref

#: One notice per item and the run whose delivery cleared it.
DELIVERY_CLEARED_KEY_PREFIX = "release-wait-delivery-cleared:"


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
            f"out. Report and end only once it reaches done."
        )
    return (
        f"{lead} Nobody holds its work claim, so no worker will close it out: "
        f"staff a session at `/yoke dash {public_ref}`, or close it out "
        f"directly with `yoke merge item {public_ref} --result ... "
        f"--verification ...`. Its evidence is on the run: "
        f"`yoke deployment-runs get {run_id}`."
    )


def _release_wait_members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Run members still standing at their own pinned release wait.

    An unreadable pin is skipped rather than guessed at: a notice sent on a
    definition this call could not interpret would name a wait that may not
    exist, and the run's own diagnostic still shows the member either way.
    """
    required = ("deployment_run_items", "items", "projects", "workflow_versions")
    if not all(_table_exists(conn, name) for name in required):
        return []
    rows = conn.execute(
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
    waiting: list[dict[str, Any]] = []
    for row in rows:
        try:
            release_stage = delivery_redirect_stage(workflow_runtime_from_row(row))
        except Exception:  # noqa: BLE001 - an unreadable pin names no wait
            continue
        if release_stage is None or str(row["status"] or "") != release_stage:
            continue
        waiting.append(
            {
                "item_id": int(row["item_id"]),
                "project_id": int(row["project_id"]),
                "public_ref": format_item_ref(
                    None, row["public_item_prefix"], row["project_sequence"]
                ),
            }
        )
    return waiting


def notify_delivery_cleared(
    conn: Any, *, run_id: str, now: Optional[datetime] = None
) -> list[dict[str, Any]]:
    """Tell every waiting member's owner that this run's delivery cleared.

    Returns one record per member with what delivery did, so a caller can
    report a notice that did not land without treating it as a run failure.
    The rows are written on the caller's transaction, matching the rest of
    the run-completion write it rides.
    """
    stamp = now or datetime.now(timezone.utc)
    reports: list[dict[str, Any]] = []
    for member in _release_wait_members(conn, run_id):
        public_ref = str(member["public_ref"])
        try:
            delivery = push_notice(
                conn,
                item_id=int(member["item_id"]),
                project_id=int(member["project_id"]),
                body_for_route=lambda route, ref=public_ref: (
                    delivery_cleared_message(
                        public_ref=ref, run_id=run_id, route=route
                    )
                ),
                idempotency_key=delivery_cleared_idempotency_key(
                    int(member["item_id"]), run_id
                ),
                now=stamp,
            )
        except Exception as exc:  # noqa: BLE001 - never reverses a delivery
            delivery = f"failed: {exc}"
        reports.append({"public_ref": public_ref, "delivery": delivery})
    return reports


__all__ = [
    "DELIVERY_CLEARED_KEY_PREFIX",
    "delivery_cleared_idempotency_key",
    "delivery_cleared_message",
    "notify_delivery_cleared",
]
