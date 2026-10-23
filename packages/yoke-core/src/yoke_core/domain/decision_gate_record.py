"""One decision as a person reading a run or an item sees it.

A run card, the run page and an item's own Approvals section draw the same
``decision_requests`` row, so they read it through one record: the request,
whether this reader may answer it, who answered it, and — for a work
approval — where it stands against the item as it is now.

A work approval's ``standing`` compares the request's frozen transition
(from stage, to stage, workflow and version) with the item's live row, the
same facts the lifecycle gate matches before it honours an answer. An answer
for a transition the item has since left, or one already consumed by a
transition the item then undid, is ``superseded``: it is history, never an
approval of the work as it stands now.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.actors import actor_name
from yoke_core.domain.decision_answers import actor_decision
from yoke_core.domain.decision_request_authority import (
    authority_reason,
    request_deciders,
)
from yoke_core.domain.decision_request_contract import LIFECYCLE_TRANSITION_APPROVAL

#: Where a work approval stands against the item's current transition.
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
COMPLETED = "completed"
SUPERSEDED = "superseded"


def lifecycle_item(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    """The live item facts a work approval's frozen transition is read against."""
    row = conn.execute(
        "SELECT status,workflow_id,workflow_version_id FROM items WHERE id=%s",
        (int(item_id),),
    ).fetchone()
    return None if row is None else {key: row[key] for key in row.keys()}


def lifecycle_standing(
    request: Mapping[str, Any], item: Optional[Mapping[str, Any]]
) -> str:
    """Where one work approval stands for the item as it is now."""
    context = request.get("subject_context") or {}
    to_stage = str(context.get("to_stage") or "")
    if item is None or request.get("status") not in ("pending", "resolved"):
        return SUPERSEDED
    if request.get("consumed_at") is not None:
        return COMPLETED if str(item["status"]) == to_stage else SUPERSEDED
    current = (
        str(context.get("from_stage") or "") == str(item["status"])
        and str(context.get("workflow_id") or "") == str(item["workflow_id"])
        and int(context.get("workflow_version_id") or 0)
        == int(item["workflow_version_id"] or 0)
    )
    if not current:
        return SUPERSEDED
    if request["status"] == "pending":
        return PENDING
    action = request.get("resolution_action")
    return APPROVED if action == "approve" else REJECTED if action == "reject" else SUPERSEDED


def gate_record(
    conn: Any, request: Mapping[str, Any], *, actor_id: Optional[int]
) -> dict[str, Any]:
    """The decision row a card draws, with this reader's authority on it."""
    request_id = int(request["id"])
    item_status = None
    standing = None
    if request["kind"] == LIFECYCLE_TRANSITION_APPROVAL:
        item = lifecycle_item(conn, int(request["subject_context"]["item_id"]))
        item_status = str(item["status"]) if item is not None else "missing"
        standing = lifecycle_standing(request, item)
    pending = request["status"] == "pending"
    reason = (
        authority_reason(conn, request_id, actor_id)
        if pending and actor_id is not None
        else None
    )
    decision = actor_decision(conn, request_id, actor_id) if actor_id is not None else None
    return {
        "request_id": request_id,
        "kind": request["kind"],
        "status": request["status"],
        "standing": standing,
        "subject_context": request["subject_context"],
        "item_status": item_status,
        "actions": request["actions"] if pending else [],
        "approval_progress": request["approval_progress"],
        "requested_at": request.get("created_at"),
        "can_act": pending and reason is not None and decision is None,
        "authority_reason": reason,
        "deciders": request_deciders(conn, request_id, actor_id),
        "your_decision": decision,
        "decided_by_you": decision is not None,
        "resolution_action": request.get("resolution_action"),
        "resolution_actor_id": request.get("resolution_actor_id"),
        "resolved_at": request.get("resolved_at"),
        "consumed_at": request.get("consumed_at"),
        "resolved_by": (
            actor_name(conn, int(request["resolution_actor_id"]))
            if request.get("resolution_actor_id") is not None
            else None
        ),
    }


__all__ = [
    "APPROVED",
    "COMPLETED",
    "PENDING",
    "REJECTED",
    "SUPERSEDED",
    "gate_record",
    "lifecycle_item",
    "lifecycle_standing",
]
