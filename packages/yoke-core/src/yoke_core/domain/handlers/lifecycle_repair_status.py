"""Registered emergency repair for an item's lifecycle status.

This is the transport-safe replacement for the source-checkout-only
``yoke_core.engines.repair_status`` entrypoint.  It uses the same canonical
backlog mutation path as normal lifecycle transitions while posting the
claim bypass on a request-scoped ContextVar, so one HTTPS request cannot leak
repair authority into another request handled by the same server process.

The dispatcher admits only an operator session.  The handler additionally
requires an operator-authored reason, validates the target against the
item's immutable workflow version, supports an optional source-status
precondition, and makes ``dry_run`` a read-only preview.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend
from yoke_core.domain.handlers.items_scalar import _map_error_code


class LifecycleRepairStatusRequest(BaseModel):
    """Payload for ``lifecycle.repair_status.execute``."""

    target_status: str = Field(..., min_length=1)
    source_status: Optional[str] = None
    reason: str = Field(..., min_length=1)
    dry_run: bool = False


class LifecycleRepairStatusResponse(BaseModel):
    """Successful repair or preview receipt."""

    item_id: int
    from_status: str
    to_status: str
    reason: str
    dry_run: bool
    changed: bool
    log: str = ""


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _read_item_state(item_id: int) -> Optional[tuple[str, Any]]:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    with db_helpers.connect() as conn:
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {_p(conn)}",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        current = row["status"] if hasattr(row, "keys") else row[0]
        workflow = load_item_workflow_runtime(conn, item_id)
    return str(current or ""), workflow


def handle_repair_status(request: FunctionCallRequest) -> HandlerOutcome:
    """Preview or apply one audited operator status repair."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _error(
            "invalid_payload",
            "lifecycle.repair_status target must carry kind='item' + item_id.",
        )
    try:
        payload = LifecycleRepairStatusRequest.model_validate(request.payload)
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")
    reason = payload.reason.strip()
    if not reason:
        return _error(
            "invalid_payload",
            "reason must contain an operator-authored reconciliation rationale.",
        )

    item_id = int(target.item_id)
    state = _read_item_state(item_id)
    if state is None:
        return _error("target_not_found", f"Item {item_id} not found.")
    current, workflow = state

    if payload.source_status and payload.source_status != current:
        return _error(
            "precondition_failed",
            f"Item {item_id} status is {current!r}, not {payload.source_status!r}.",
        )

    from yoke_core.engines.repair_status_item import (
        _validate_item_target_status,
    )

    validation_error = _validate_item_target_status(
        workflow,
        payload.target_status,
    )
    if validation_error:
        return _error("validation_error", validation_error)

    changed = current != payload.target_status
    if payload.dry_run or not changed:
        response = LifecycleRepairStatusResponse(
            item_id=item_id,
            from_status=current,
            to_status=payload.target_status,
            reason=reason,
            dry_run=payload.dry_run,
            changed=changed,
        )
        return HandlerOutcome(result_payload=response.model_dump())

    from yoke_core.domain import backlog
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.backlog_status_write_precondition import (
        WORKFLOW_STATUS_PRECONDITION_FAILED,
    )
    from yoke_core.domain.status_claim_bypass_context import (
        status_bypass_override,
    )

    repair_source = f"repair-status:{reason}"
    captured = io.StringIO()
    with status_bypass_override(
        claim_bypass=repair_source,
        status_source=repair_source,
        task_done_verified=payload.target_status == "done",
    ):
        result: Dict[str, Any] = backlog.execute_update(
            item_id=item_id,
            field="status",
            value=payload.target_status,
            done_nonce_verified=payload.target_status == "done",
            qa_bypass=False,
            rebuild_board=True,
            out=captured,
            expected_status=current,
            session_id=request.actor.session_id,
            originator_actor_id=numeric_actor_id(request.actor.actor_id),
        )

    if not result.get("success"):
        legacy_code = result.get("error_code")
        if legacy_code == WORKFLOW_STATUS_PRECONDITION_FAILED:
            code = "precondition_failed"
        elif legacy_code == "GATE_APPROVAL_REQUIRED":
            code = "approval_required"
        else:
            code = _map_error_code(legacy_code)
        return _error(
            code,
            str(result.get("error") or "lifecycle status repair failed"),
        )

    response = LifecycleRepairStatusResponse(
        item_id=item_id,
        from_status=current,
        to_status=payload.target_status,
        reason=reason,
        dry_run=False,
        changed=True,
        log=captured.getvalue(),
    )
    return HandlerOutcome(result_payload=response.model_dump())


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "lifecycle.repair_status.execute",
        "handler": handle_repair_status,
        "request_model": LifecycleRepairStatusRequest,
        "response_model": LifecycleRepairStatusResponse,
        "stability": "stable",
        "owner_module": ("yoke_core.domain.handlers.lifecycle_repair_status"),
        "target_kinds": ["item"],
        "side_effects": [
            "render_body",
            "rebuild_board",
            "github_sync",
            "emit_item_status_changed",
            "epic_task_cascade",
        ],
        "emitted_event_names": [
            "YokeFunctionCalled",
            "ClaimVerificationBypassed",
            "ItemStatusChanged",
        ],
        "guardrails": [
            "operator_override_required",
            "workflow_stage_validation",
            "precondition_source_status",
            "operator_reason_required",
        ],
        "adapter_status": "live",
        "claim_required_kind": "operator_override",
    },
]


__all__ = [
    "LifecycleRepairStatusRequest",
    "LifecycleRepairStatusResponse",
    "REGISTRATIONS",
    "handle_repair_status",
]
