"""First-class item cancel: claim, close, and release in one call.

``items.cancel.run`` consumes :func:`backlog_close_op.execute_close` so
dependency reconciliation and GitHub close/comment are not skipped. The
work claim still governs the write with the same implicit acquire as the
flag verbs: take-and-release when nobody holds it, refuse a foreign
holder. Unlike freeze, a successful cancel also releases a claim the
caller already held, because the item is terminal.

A frozen item is cancelled in this same call. Freeze parks work that
will resume; cancel is terminal, so ``execute_close`` clears ``frozen``
as part of the close rather than demanding a separate thaw.
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
from yoke_core.domain.handlers.items_flags_claim import (
    _ClaimRefused,
    _acquire_for_caller,
    _release_acquired,
)


class CancelRequest(BaseModel):
    """Payload for ``items.cancel.run``."""

    reason: str = Field(
        ...,
        description="One-line cancellation reason stored in items.resolution.",
    )
    ref: Optional[str] = Field(
        default=None,
        description="Optional superseding item PREFIX-N stored as resolution_ref.",
    )


class CancelResponse(BaseModel):
    """Post-close item state plus whether this call changed anything."""

    item_id: int
    public_ref: str
    status: str
    reason: str
    ref: Optional[str] = None
    frozen_cleared: bool
    changed: bool
    dependency_reconciliation: Optional[Dict[str, Any]] = None
    log: str = ""


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _cell(row: Any, index: int, name: str) -> Any:
    return row[name] if hasattr(row, "keys") else row[index]


def _load_state(item_id: int) -> Optional[Dict[str, Any]]:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import render_item_ref

    with db_helpers.connect() as conn:
        from yoke_core.domain import db_backend

        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT status, frozen, resolution, resolution_ref FROM items "
            f"WHERE id = {marker}",
            (int(item_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "public_ref": render_item_ref(conn, int(item_id)),
            "status": str(_cell(row, 0, "status") or ""),
            "frozen": bool(_cell(row, 1, "frozen")),
            "resolution": _cell(row, 2, "resolution"),
            "resolution_ref": _cell(row, 3, "resolution_ref"),
        }


def _close_failure(message: str) -> HandlerOutcome:
    lowered = message.lower()
    if "not found" in lowered:
        code = "not_found"
    elif "already done" in lowered:
        code = "item_done"
    elif "non-empty" in lowered or "single line" in lowered:
        code = "invalid_payload"
    else:
        code = "precondition_failed"
    return _error(code, message)


def handle_cancel(request: FunctionCallRequest) -> HandlerOutcome:
    """Cancel the target item through ``execute_close`` under an implicit claim."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _error(
            "invalid_payload",
            "items.cancel.run target must carry kind='item' + item_id.",
        )
    try:
        payload = CancelRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")
    item_id = int(target.item_id)
    state = _load_state(item_id)
    if state is None:
        return _error("not_found", f"item {item_id} not found")
    public_ref = str(state["public_ref"])
    from yoke_core.domain.backlog_cancellation import normalize_cancellation_reason

    reason, reason_error = normalize_cancellation_reason(payload.reason)
    if reason_error or reason is None:
        return _error("invalid_payload", str(reason_error or "reason required"))
    captured = io.StringIO()
    try:
        acquired = _acquire_for_caller(
            item_id,
            public_ref,
            str(request.actor.session_id or ""),
            reason="item cancel",
        )
    except _ClaimRefused as refused:
        return _error(
            "claim_held",
            f"{refused.public_ref} is claimed by session {refused.holder}; "
            "coordinate with the holder before cancelling it.",
        )
    try:
        from yoke_core.domain.backlog_close_op import execute_close

        result = execute_close(
            item_id,
            reason,
            resolution_ref=payload.ref,
            out=captured,
            session_id=request.actor.session_id,
        )
    finally:
        _release_acquired(acquired, reason="item cancel complete")
    if not result.get("success"):
        return _close_failure(str(result.get("error") or "cancel failed"))
    final = _load_state(item_id) or state
    changed = not bool(result.get("noop"))
    response = CancelResponse(
        item_id=item_id,
        public_ref=str(final["public_ref"]),
        status=str(final["status"]),
        reason=str(final.get("resolution") or reason),
        ref=final.get("resolution_ref") or payload.ref,
        frozen_cleared=bool(state["frozen"]) and not bool(final["frozen"]),
        changed=changed,
        dependency_reconciliation=result.get("dependency_reconciliation"),
        log=captured.getvalue(),
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "items.cancel.run",
        "handler": handle_cancel,
        "request_model": CancelRequest,
        "response_model": CancelResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_cancel",
        "target_kinds": ["item"],
        "side_effects": [
            "render_body",
            "rebuild_board",
            "github_sync",
            "cancel_item",
        ],
        "emitted_event_names": ["YokeFunctionCalled", "ItemStatusChanged"],
        "guardrails": ["implicit_item_claim", "execute_close"],
        "adapter_status": "live",
        "claim_required_kind": None,
    }
]


__all__ = [
    "CancelRequest",
    "CancelResponse",
    "REGISTRATIONS",
    "handle_cancel",
]
