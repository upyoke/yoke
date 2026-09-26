"""Owner approval selected by a Dash item's approval-on-done posture."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.approval_policy import ApprovalPolicy
from yoke_core.domain.dash_posture_read import (
    failure as _failure,
    item_row as _item,
    posture as _posture,
)


def approval_policy_for_posture(
    *,
    workflow_id: str,
    posture: Mapping[str, Any],
    target_status: str,
) -> Optional[ApprovalPolicy]:
    """Return the explicit owner gate selected by Dash approval posture."""
    if (
        workflow_id != "dash"
        or target_status != "done"
        or posture.get("approval_on_done") is not True
    ):
        return None
    return ApprovalPolicy(roles=("owner",))


def approval_policy_for_transition(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
) -> Optional[ApprovalPolicy]:
    """Return the explicit owner authority selected by approval-on-done."""
    item = _item(conn, item_id)
    return approval_policy_for_posture(
        workflow_id=str(item["workflow_id"]),
        posture=_posture(item),
        target_status=target_status,
    )


def approval_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    """Refuse done until an owner approved this item's done transition."""
    from yoke_core.domain.decision_requests import list_subject_requests

    history = list_subject_requests(
        conn,
        "item_transition",
        f"{int(item_id)}:done",
    )
    latest = history[0] if history else None
    if (
        latest is not None
        and latest["status"] == "resolved"
        and latest["resolution_action"] == "approve"
    ):
        return None
    from yoke_core.domain.decision_request_authority import request_deciders

    if (
        latest is not None
        and latest["status"] == "pending"
        and not request_deciders(conn, int(latest["id"]))
    ):
        return _failure(
            "GATE_DASH_APPROVAL_REQUIRED",
            "Approval-on-done has no eligible human project owner who can answer.",
            "Grant the project owner role to a human actor, then resolve the "
            "Inbox request. Do not assign roles automatically.",
        )
    return _failure(
        "GATE_DASH_APPROVAL_REQUIRED",
        "Approval-on-done is waiting for a project owner decision.",
        "Resolve the lifecycle decision request through the Inbox.",
    )


__all__ = [
    "approval_gate",
    "approval_policy_for_posture",
    "approval_policy_for_transition",
]
