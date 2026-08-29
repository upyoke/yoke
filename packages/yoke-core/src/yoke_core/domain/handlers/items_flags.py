"""Handlers for the item coordination-flag verbs.

``items.freeze.run`` / ``items.thaw.run`` toggle ``items.frozen``;
``items.block.run`` / ``items.unblock.run`` toggle ``items.blocked``
together with ``items.blocked_reason``.

Claim handling is implicit, not absent. The caller does not write the
acquire/release choreography by hand, but the work claim still governs
the write: with no live claim the handler acquires one and releases what
it acquired; when the calling session already holds the claim it
proceeds and leaves that claim untouched; when a different live session
holds it the call is refused, naming the holder. See
:mod:`items_flags_claim` for why the acquire is attempted before the
holder is read.

A frozen item still accepts block and unblock — the frozen guard on
``items.scalar.update`` stops content drift on a parked item, and
recording why a parked item is also blocked is coordination, not drift.

``blocked_reason`` is written before ``blocked``, and cleared after it on
unblock, because every reader keys on the flag and none surfaces a
reason without it (:func:`render_blocked_section` returns ``None``
unless ``blocked`` is set). The flag write is therefore the single
observable commit point, so a failure between the two writes can never
leave a half-applied block.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest, FunctionError, HandlerOutcome,
)
from yoke_core.domain.handlers.items_flags_claim import (
    _ClaimRefused, _acquire_for_caller, _release_acquired,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FlagRequest(BaseModel):
    """Empty payload — freeze, thaw, unblock take only the target."""


class BlockRequest(BaseModel):
    """Payload for ``items.block.run``."""

    reason: str = Field(
        ...,
        description="Operator-supplied reason, stored verbatim in items.blocked_reason.",
    )


class FlagResponse(BaseModel):
    """Post-write flag state plus whether this call changed anything."""

    item_id: int
    public_ref: str
    status: str
    frozen: bool
    blocked: bool
    blocked_reason: Optional[str] = None
    changed: bool
    log: str = ""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _cell(row: Any, index: int, name: str) -> Any:
    """Read one column from a tuple row or a mapping row."""
    return row[name] if hasattr(row, "keys") else row[index]


def _load_state(item_id: int) -> Optional[Dict[str, Any]]:
    """Return the item's ref plus its current status and flag values."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import render_item_ref

    with db_helpers.connect() as conn:
        from yoke_core.domain import db_backend

        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT status, frozen, blocked, blocked_reason FROM items "
            f"WHERE id = {marker}",
            (int(item_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "public_ref": render_item_ref(conn, int(item_id)),
            "status": str(_cell(row, 0, "status") or ""),
            "frozen": bool(_cell(row, 1, "frozen")),
            "blocked": bool(_cell(row, 2, "blocked")),
            "blocked_reason": _cell(row, 3, "blocked_reason"),
        }


def _prepare(
    request: FunctionCallRequest, model: type[BaseModel], function_id: str
) -> Tuple[Optional[int], Optional[Any], Optional[Dict[str, Any]], Optional[HandlerOutcome]]:
    """Validate the envelope and load current state, or return a refusal."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return None, None, None, _error(
            "invalid_payload",
            f"{function_id} target must carry kind='item' + item_id.",
        )
    try:
        payload = model.model_validate(request.payload or {})
    except Exception as exc:
        return None, None, None, _error("invalid_payload", f"payload invalid: {exc}")
    state = _load_state(int(target.item_id))
    if state is None:
        return None, None, None, _error(
            "not_found", f"item {target.item_id} not found"
        )
    return int(target.item_id), payload, state, None


def _apply(
    item_id: int,
    public_ref: str,
    writes: List[Tuple[str, Any]],
    request: FunctionCallRequest,
    captured: io.StringIO,
) -> Optional[HandlerOutcome]:
    """Apply the verb's writes under the caller's work claim.

    Returns a refusal outcome when another session holds the claim or a
    write fails, else None.
    """
    try:
        acquired = _acquire_for_caller(
            item_id, public_ref, str(request.actor.session_id or "")
        )
    except _ClaimRefused as refused:
        return _error(
            "claim_held",
            f"{refused.public_ref} is claimed by session {refused.holder}; "
            "coordinate with the holder before changing its coordination flags.",
        )
    try:
        for field, value in writes:
            error = _write(item_id, field, value, request, captured)
            if error is not None:
                return _error("write_failed", error)
    finally:
        _release_acquired(acquired)
    return None


def _write(
    item_id: int,
    field: str,
    value: Any,
    request: FunctionCallRequest,
    captured: io.StringIO,
) -> Optional[str]:
    """Apply one flag field write. Returns an error message, or None."""
    from yoke_core.domain import backlog
    from yoke_core.domain.actor_project_visibility import numeric_actor_id

    result = backlog.execute_update(
        item_id=int(item_id),
        field=field,
        value=value,
        session_id=request.actor.session_id,
        out=captured,
        originator_actor_id=numeric_actor_id(request.actor.actor_id),
    )
    if result.get("success"):
        return None
    return str(result.get("error") or f"{field} update failed")


def _done(
    item_id: int, state: Dict[str, Any], changed: bool, captured: io.StringIO
) -> HandlerOutcome:
    """Re-read the post-write state and build the success envelope."""
    final = _load_state(item_id) or state
    response = FlagResponse(
        item_id=item_id,
        public_ref=str(final["public_ref"]),
        status=str(final["status"]),
        frozen=bool(final["frozen"]),
        blocked=bool(final["blocked"]),
        blocked_reason=final["blocked_reason"],
        changed=changed,
        log=captured.getvalue(),
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_freeze(request: FunctionCallRequest) -> HandlerOutcome:
    """Set ``frozen=true``, refusing a done item and no-opping when frozen."""
    item_id, _payload, state, refusal = _prepare(
        request, FlagRequest, "items.freeze.run"
    )
    if refusal is not None:
        return refusal
    if state["status"] == "done":
        return _error(
            "item_done",
            f"Cannot freeze {state['public_ref']}: the item is done. Advance it "
            "back into an in-flight status first.",
        )
    captured = io.StringIO()
    if state["frozen"]:
        return _done(item_id, state, False, captured)
    failure = _apply(
        item_id, state["public_ref"], [("frozen", True)], request, captured
    )
    return failure or _done(item_id, state, True, captured)


def handle_thaw(request: FunctionCallRequest) -> HandlerOutcome:
    """Clear frozen after dormant path claims revalidate against live overlap."""
    item_id, _payload, state, refusal = _prepare(
        request, FlagRequest, "items.thaw.run"
    )
    if refusal is not None:
        return refusal
    captured = io.StringIO()
    if not state["frozen"]:
        return _done(item_id, state, False, captured)
    from yoke_core.domain.path_claims_thaw import revalidate_item_path_claims_on_thaw
    revalidate_item_path_claims_on_thaw(int(item_id))
    failure = _apply(
        item_id, state["public_ref"], [("frozen", False)], request, captured
    )
    return failure or _done(item_id, state, True, captured)


def handle_block(request: FunctionCallRequest) -> HandlerOutcome:
    """Record the reason then set ``blocked=true``; replaces a stale reason."""
    item_id, payload, state, refusal = _prepare(
        request, BlockRequest, "items.block.run"
    )
    if refusal is not None:
        return refusal
    reason = str(payload.reason).strip()
    if not reason:
        return _error("validation_error", "reason must be a non-empty string.")
    if state["status"] == "done":
        return _error(
            "item_done",
            f"Cannot block {state['public_ref']}: the item is done. Advance it "
            "back into an in-flight status first.",
        )
    captured = io.StringIO()
    changed = not state["blocked"] or str(state["blocked_reason"] or "") != reason
    if not changed:
        return _done(item_id, state, False, captured)
    writes: List[Tuple[str, Any]] = [("blocked_reason", reason)]
    if not state["blocked"]:
        writes.append(("blocked", True))
    failure = _apply(item_id, state["public_ref"], writes, request, captured)
    return failure or _done(item_id, state, True, captured)


def handle_unblock(request: FunctionCallRequest) -> HandlerOutcome:
    """Clear ``blocked`` then its reason, no-opping when not blocked."""
    item_id, _payload, state, refusal = _prepare(
        request, FlagRequest, "items.unblock.run"
    )
    if refusal is not None:
        return refusal
    captured = io.StringIO()
    if not state["blocked"]:
        return _done(item_id, state, False, captured)
    failure = _apply(
        item_id,
        state["public_ref"],
        [("blocked", False), ("blocked_reason", None)],
        request,
        captured,
    )
    return failure or _done(item_id, state, True, captured)


# ---------------------------------------------------------------------------
# Registration descriptors
# ---------------------------------------------------------------------------


def _descriptor(
    function_id: str, handler: Any, request_model: type[BaseModel], summary: str
) -> Dict[str, Any]:
    return {
        "function_id": function_id,
        "handler": handler,
        "request_model": request_model,
        "response_model": FlagResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_flags",
        "target_kinds": ["item"],
        "side_effects": ["render_body", "rebuild_board", "github_sync", summary],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": ["implicit_item_claim", "done_item_block"],
        "adapter_status": "live",
        # None at the dispatcher on purpose: its gate would refuse before
        # the handler could acquire for the caller. The claim boundary is
        # enforced in the handler, as claims.work.release_session_scoped.
        "claim_required_kind": None,
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _descriptor("items.freeze.run", handle_freeze, FlagRequest, "set_frozen"),
    _descriptor("items.thaw.run", handle_thaw, FlagRequest, "clear_frozen"),
    _descriptor("items.block.run", handle_block, BlockRequest, "set_blocked"),
    _descriptor("items.unblock.run", handle_unblock, FlagRequest, "clear_blocked"),
]


__all__ = [
    "BlockRequest",
    "FlagRequest",
    "FlagResponse",
    "REGISTRATIONS",
    "handle_block",
    "handle_freeze",
    "handle_thaw",
    "handle_unblock",
]
