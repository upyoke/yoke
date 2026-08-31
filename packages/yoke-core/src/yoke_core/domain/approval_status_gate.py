"""Read-side status gate for a lifecycle approval already requested.

A definition may list this gate on a stage before the project has anyone
authorized to answer it. Refusing there strands the item behind a decision
nobody can make, so an undeclared approval authority makes the gate ABSENT
rather than blocking: the obligation arrives with the roster that can
satisfy it. Absence is recorded as ``WorkflowGateAbsent`` so the skip is
countable instead of silent.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.approval_gate import (
    _item_context,
    _matches_transition_snapshot,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.decision_requests import list_subject_requests
from yoke_core.domain.workflow_gate_absence import record_gate_absence
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def evaluate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Require the latest declared transition approval to resolve as approve."""
    conn = connect(db_path)
    try:
        workflow = load_item_workflow_runtime(conn, int(item_id))
        configured = dict(workflow.policies.get("approval_defaults", {})).get(
            target_status
        )
        if not configured:
            # Same authority resolution the preflight uses when it decides
            # whether to create the decision request at all, so the gate and
            # the request agree about who — if anyone — may answer.
            from yoke_core.domain.dash_posture_gate import (
                approval_policy_for_transition,
            )

            configured = approval_policy_for_transition(
                conn,
                item_id=int(item_id),
                target_status=target_status,
            )
        if not configured:
            record_gate_absence(
                gate_id="approval",
                item_id=int(item_id),
                target_status=target_status,
                reason="approval_authority_undeclared",
                detail=(
                    "neither the pinned workflow nor the item's posture "
                    "declares an approving role or actor for "
                    f"{target_status!r}"
                ),
                conn=conn,
            )
            return None
        history = list_subject_requests(
            conn,
            "item_transition",
            f"{int(item_id)}:{target_status}",
        )
        item = _item_context(conn, int(item_id))
    finally:
        conn.close()
    latest = history[0] if history else None
    if (
        latest is not None
        and latest["status"] == "resolved"
        and latest["resolution_action"] == "approve"
        and _matches_transition_snapshot(latest, item, target_status)
    ):
        return None
    request = f" {latest['id']}" if latest is not None else ""
    return {
        "success": False,
        "error_code": "GATE_APPROVAL_REQUIRED",
        "error": (
            "The declared lifecycle approval has not been resolved as "
            f"approve (decision request{request or ' missing'})."
        ),
        "remediation_hint": (
            "Resolve the decision request through an authorized Inbox action."
        ),
    }


__all__ = ["evaluate"]
