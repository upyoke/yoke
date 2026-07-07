"""Handler for the ``lifecycle.transition`` function id.

Convenience surface over ``items.scalar.update`` that names the source
status, target status, and transition reason explicitly. Routes through
the same ``backlog.execute_update`` that ``items update ... status …``
and the PATCH route both call, so claim verification, the authoritative
status gate, the QA gates, the epic-task cascade, and GitHub-sync side
effects fire once regardless of which adapter the operator chose.

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
            "Human-readable rationale recorded with the call. Persisted in the "
            "envelope JSON via the dispatcher's YokeFunctionCalled event."
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
    rework_count: Optional[int] = None
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


def _read_current_status(item_id: int) -> Optional[str]:
    from yoke_core.domain import db_helpers
    with db_helpers.connect() as conn:
        p = _p(conn)
        row = conn.execute(
            f"SELECT status, frozen FROM items WHERE id = {p}", (int(item_id),),
        ).fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return str(row["status"] or "")
    return str(row[0] or "")


def _frozen_blocked(item_id: int, force: bool) -> Optional[HandlerOutcome]:
    """Mirror the items.scalar.update frozen pre-check for status writes."""
    if force:
        return None
    from yoke_core.domain import db_helpers
    with db_helpers.connect() as conn:
        p = _p(conn)
        row = conn.execute(
            f"SELECT frozen FROM items WHERE id = {p}", (int(item_id),),
        ).fetchone()
    if row is None:
        return None
    frozen_val = row[0] if not hasattr(row, "keys") else row["frozen"]
    if not frozen_val:
        return None
    return _error_outcome(
        "frozen",
        f"YOK-{item_id} is frozen; thaw the item before transitioning "
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
    current = _read_current_status(item_id)
    if current is None:
        return _error_outcome(
            "target_not_found", f"YOK-{item_id} not found.",
        )

    if payload.source_status and payload.source_status != current:
        return _error_outcome(
            "precondition_failed",
            f"YOK-{item_id} status is {current!r}, not {payload.source_status!r}.",
        )

    blocked = _frozen_blocked(item_id, payload.force)
    if blocked is not None:
        return blocked

    from yoke_core.domain import backlog

    captured = io.StringIO()
    result: Dict[str, Any] = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=payload.target_status,
        done_nonce_verified=payload.done_nonce_verified,
        force=payload.force,
        qa_bypass=payload.qa_bypass,
        session_id=request.actor.session_id,
        out=captured,
    )

    if not result.get("success"):
        legacy_code = result.get("error_code")
        return _error_outcome(
            _map_error_code(legacy_code),
            str(result.get("error") or "lifecycle transition failed"),
        )

    response = LifecycleTransitionResponse(
        item_id=item_id,
        from_status=current,
        to_status=payload.target_status,
        reason=payload.reason,
        rework_count=result.get("rework_count"),
        log=captured.getvalue(),
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
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
            "render_body", "rebuild_board", "github_sync",
            "emit_item_status_changed", "epic_task_cascade",
        ],
        "emitted_event_names": [
            "YokeFunctionCalled", "ItemStatusChanged",
        ],
        "guardrails": ["claim_required", "frozen_item_block", "precondition_source_status"],
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
