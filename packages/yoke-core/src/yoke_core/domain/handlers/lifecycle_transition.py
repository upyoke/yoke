"""Handler for the ``lifecycle.transition`` function id.

Convenience surface over ``items.scalar.update`` that names the source
status, target status, and transition reason explicitly. Routes through
the same ``backlog.execute_update`` as typed scalar status updates, so
claim verification, the authoritative status gate, the QA gates, the
epic-task cascade, and GitHub-sync side effects fire once regardless of
which canonical adapter the operator chose.

The ``source_status`` field is a precondition: when supplied, the
handler verifies it matches the live ``items.status`` before issuing
the write. A mismatch returns ``error.code="precondition_failed"`` so
operators see a coherent diagnostic instead of a downstream gate that
"happens" to reject the transition.

Future-concept absorption target: when the execution journal lands,
this handler becomes a typed journal entry plus the same
``execute_update`` call; this module is absorbed into the journal hot
path.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import db_backend
from yoke_core.domain.board_rebuild_failure import BOARD_REBUILD_FAILED_EVENT_NAME
from yoke_core.domain.handlers.items_scalar import _map_error_code
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class LifecycleTransitionRequest(BaseModel):
    """Payload for ``lifecycle.transition``."""

    target_status: str = Field(
        ..., description="New value for items.status (the canonical lifecycle name)."
    )
    source_status: Optional[str] = Field(
        None,
        description=(
            "Optional precondition: handler verifies items.status matches "
            "before issuing the write."
        ),
    )
    reason: Optional[str] = Field(
        None,
        description=(
            "Human-readable rationale recorded with the call. When cancelling, "
            "this must be a non-empty one-line reason and is stored in "
            "items.resolution."
        ),
    )
    done_nonce_verified: bool = False
    force: bool = False
    qa_bypass: bool = False


class LifecycleTransitionResponse(BaseModel):
    """Successful result envelope."""

    item_id: int
    from_status: str
    to_status: str
    reason: Optional[str] = None
    log: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_outcome(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _read_current_status(item_id: int) -> tuple[Optional[str], str]:
    """Return ``(status, public_ref)``; status is ``None`` when the item is gone.

    The public ref is read alongside the status so the caller's operator
    messages name the item the way the operator does.
    """
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import render_item_ref

    with db_helpers.connect() as conn:
        p = _p(conn)
        row = conn.execute(
            f"SELECT status, frozen FROM items WHERE id = {p}",
            (int(item_id),),
        ).fetchone()
        public_ref = render_item_ref(conn, int(item_id))
    if row is None:
        return None, public_ref
    if hasattr(row, "keys"):
        return str(row["status"] or ""), public_ref
    return str(row[0] or ""), public_ref


def _frozen_blocked(item_id: int, force: bool) -> Optional[HandlerOutcome]:
    """Mirror the items.scalar.update frozen pre-check for status writes."""
    if force:
        return None
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import render_item_ref

    with db_helpers.connect() as conn:
        p = _p(conn)
        row = conn.execute(
            f"SELECT frozen FROM items WHERE id = {p}",
            (int(item_id),),
        ).fetchone()
        public_ref = render_item_ref(conn, int(item_id))
    if row is None:
        return None
    frozen_val = row[0] if not hasattr(row, "keys") else row["frozen"]
    if not frozen_val:
        return None
    return _error_outcome(
        "frozen",
        f"{public_ref} is frozen; thaw the item before transitioning "
        f"status (or pass force=True for sanctioned overrides).",
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handle_transition(request: FunctionCallRequest) -> HandlerOutcome:
    """Route a typed lifecycle transition through ``backlog.execute_update``."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _error_outcome(
            "invalid_payload",
            "lifecycle.transition target must carry kind='item' + item_id.",
        )
    try:
        payload = LifecycleTransitionRequest.model_validate(request.payload)
    except Exception as exc:
        return _error_outcome("invalid_payload", f"payload invalid: {exc}")

    item_id = int(target.item_id)
    from yoke_core.domain import backlog
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.backlog_status_write_precondition import (
        WORKFLOW_STATUS_PRECONDITION_FAILED,
    )
    from yoke_core.domain.db_mutation_gate_loaders import acting_item_ref_bound
    from yoke_core.domain.backlog_db_mutation_gate_runner import (
        capture_db_mutation_gate_warnings,
    )

    current, public_ref = _read_current_status(item_id)
    if current is None:
        return _error_outcome(
            "target_not_found",
            f"{public_ref} not found.",
        )
    if payload.source_status and payload.source_status != current:
        return _error_outcome(
            "precondition_failed",
            f"{public_ref} status is {current!r}, not {payload.source_status!r}.",
        )
    blocked = _frozen_blocked(item_id, payload.force)
    if blocked is not None:
        return blocked

    cancellation_reason = payload.reason
    if payload.target_status == "cancelled":
        from yoke_core.domain.backlog_cancellation import normalize_cancellation_reason

        cancellation_reason, reason_error = normalize_cancellation_reason(
            payload.reason
        )
        if reason_error:
            return _error_outcome("invalid_payload", reason_error)

    captured = io.StringIO()
    with (
        acting_item_ref_bound(target.public_ref),
        capture_db_mutation_gate_warnings() as gate_warnings,
    ):
        result = backlog.execute_update(
            item_id=item_id,
            field="status",
            value=payload.target_status,
            resolution=cancellation_reason,
            done_nonce_verified=payload.done_nonce_verified,
            force=payload.force,
            qa_bypass=payload.qa_bypass,
            session_id=request.actor.session_id,
            out=captured,
            expected_status=current,
            originator_actor_id=numeric_actor_id(request.actor.actor_id),
            rebuild_board=False,
        )
        if result.get("success"):
            backlog._maybe_rebuild_board(True, out=captured)

    if not result.get("success"):
        legacy_code = result.get("error_code")
        if legacy_code == WORKFLOW_STATUS_PRECONDITION_FAILED:
            return _error_outcome(
                "precondition_failed",
                str(result.get("error") or "workflow changed during transition"),
            )
        if legacy_code == "GATE_APPROVAL_REQUIRED":
            return _error_outcome(
                "approval_required",
                str(result.get("error") or "lifecycle approval is required"),
            )
        return _error_outcome(
            _map_error_code(legacy_code),
            str(result.get("error") or "lifecycle transition failed"),
        )

    response = LifecycleTransitionResponse(
        item_id=item_id,
        from_status=current,
        to_status=payload.target_status,
        reason=cancellation_reason
        if payload.target_status == "cancelled"
        else payload.reason,
        log=captured.getvalue(),
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
        warnings=gate_warnings,
    )


# ---------------------------------------------------------------------------
# Registration descriptor
# ---------------------------------------------------------------------------


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        # The registry requires the three-segment
        # ``<family>.<subfamily>.<operation>`` id shape, so the two-segment
        # ``lifecycle.transition`` name is expressed as family=lifecycle,
        # subfamily=transition, operation=execute. Callers that read the
        # entry back via ``lookup(...)`` rely on this canonical id.
        "function_id": "lifecycle.transition.execute",
        "handler": handle_transition,
        "request_model": LifecycleTransitionRequest,
        "response_model": LifecycleTransitionResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.lifecycle_transition",
        "target_kinds": ["item"],
        "side_effects": [
            "render_body",
            "rebuild_board",
            "github_sync",
            "emit_item_status_changed",
            "epic_task_cascade",
        ],
        "emitted_event_names": [
            BOARD_REBUILD_FAILED_EVENT_NAME,
            "YokeFunctionCalled",
            "ItemStatusChanged",
        ],
        "guardrails": [
            "claim_required",
            "frozen_item_block",
            "precondition_source_status",
        ],
        "adapter_status": "live",
        "claim_required_kind": "item",
    },
]


__all__ = [
    "handle_transition",
    "LifecycleTransitionRequest",
    "LifecycleTransitionResponse",
    "REGISTRATIONS",
]
