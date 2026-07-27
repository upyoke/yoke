"""Read-side status gate for a lifecycle approval already requested."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.decision_requests import list_subject_requests
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
            return {
                "success": False,
                "error_code": "GATE_APPROVAL_UNCONFIGURED",
                "error": (
                    f"Workflow gate 'approval' at {target_status!r} has no "
                    "declared role or actor authority."
                ),
            }
        history = list_subject_requests(
            conn,
            "item_transition",
            f"{int(item_id)}:{target_status}",
        )
    finally:
        conn.close()
    latest = history[0] if history else None
    if (
        latest is not None
        and latest["status"] == "resolved"
        and latest["resolution_action"] == "approve"
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
