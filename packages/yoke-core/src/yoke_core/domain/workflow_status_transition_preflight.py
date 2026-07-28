"""Canonical QA materialization and approval preflight for status writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


@dataclass(frozen=True)
class StatusTransitionPreflight:
    workflow_version_id: int
    source_status: str
    approval_request_id: Optional[int] = None
    failure: Optional[dict[str, Any]] = None


def prepare_status_transition(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
    originator_actor_id: Optional[int],
    session_id: str,
    expected_status: Optional[str] = None,
) -> StatusTransitionPreflight:
    """Materialize QA and evaluate approval against one workflow snapshot."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock_item_workflow_bindings(conn, (int(item_id),))
    item = conn.execute(
        f"SELECT status FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if item is None:
        conn.rollback()
        return StatusTransitionPreflight(
            workflow_version_id=0,
            source_status="",
            failure={
                "success": False,
                "error_code": "NOT_FOUND",
                "error": f"Item YOK-{item_id} not found",
            },
        )
    current_status = str(item["status"] if hasattr(item, "keys") else item[0])
    if expected_status is not None and current_status != expected_status:
        from yoke_core.domain.backlog_status_write_precondition import (
            WORKFLOW_STATUS_PRECONDITION_FAILED,
        )

        conn.rollback()
        return StatusTransitionPreflight(
            workflow_version_id=0,
            source_status=current_status,
            failure={
                "success": False,
                "error_code": WORKFLOW_STATUS_PRECONDITION_FAILED,
                "error": (
                    f"item status changed before transition preflight; "
                    f"expected {expected_status!r}, found "
                    f"{current_status!r}"
                ),
            },
        )
    workflow = load_item_workflow_runtime(conn, item_id)
    if not workflow.accepts_stage(target_status):
        valid = ", ".join(workflow.stage_ids)
        conn.rollback()
        return StatusTransitionPreflight(
            workflow_version_id=int(workflow.workflow_version_id),
            source_status=current_status,
            failure={
                "success": False,
                "error_code": "VALIDATION_ERROR",
                "error": (
                    f"'{target_status}' is not a valid stage for "
                    f"{workflow.workflow_id}@{workflow.version}. "
                    f"Defined stages: {valid} (plus universal exceptional "
                    "stages blocked, stopped, failed, cancelled)."
                ),
            },
        )
    if _table_exists(conn, "qa_plan_project_defaults"):
        from yoke_core.domain.qa_plan_attachments import (
            has_attached_plans,
            materialize_for_item,
        )

        if has_attached_plans(
            conn,
            item_id=item_id,
            transition_id=target_status,
        ):
            materialize_for_item(
                conn,
                item_id=item_id,
                transition_id=target_status,
                commit=False,
            )
    workflow_version_id = int(workflow.workflow_version_id)
    approval = dict(workflow.policies.get("approval_defaults", {})).get(target_status)
    if not approval:
        from yoke_core.domain.dash_posture_gate import (
            approval_policy_for_transition,
        )

        approval = approval_policy_for_transition(
            conn,
            item_id=item_id,
            target_status=target_status,
        )
    if not approval:
        conn.commit()
        return StatusTransitionPreflight(
            workflow_version_id=workflow_version_id,
            source_status=current_status,
        )

    from yoke_core.domain.approval_gate import evaluate_lifecycle_approval

    verdict = evaluate_lifecycle_approval(
        conn,
        item_id=item_id,
        to_stage_id=target_status,
        role_names=approval.get("roles", ()),
        named_actor_ids=approval.get("actors", ()),
        originator_actor_id=originator_actor_id,
        session_id=session_id,
    )
    # Approval evaluation may return an already-resolved decision without
    # creating a new row. End the preflight transaction in every verdict
    # branch so downstream gates can safely use their own connections.
    conn.commit()
    if verdict.satisfied:
        return StatusTransitionPreflight(
            workflow_version_id=workflow_version_id,
            source_status=current_status,
            approval_request_id=int(verdict.request_id),
        )
    return StatusTransitionPreflight(
        workflow_version_id=workflow_version_id,
        source_status=current_status,
        failure={
            "success": False,
            "error_code": "GATE_APPROVAL_REQUIRED",
            "error": (f"{verdict.reason} (decision request {verdict.request_id})"),
        },
    )


__all__ = ["StatusTransitionPreflight", "prepare_status_transition"]
