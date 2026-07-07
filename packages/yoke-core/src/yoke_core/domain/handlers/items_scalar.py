"""Handler for the ``items.scalar.update`` function id.

Delegates to :func:`yoke_core.domain.backlog.execute_update` so the
function-call surface and the existing PATCH /v1/items/{id} route share
one gate path (:func:`yoke_core.domain.mutations.prepare_update` plus
the authoritative status gate, claim verification, epic-task cascade,
and GitHub-sync side effects). The handler does NOT duplicate gate
logic — it only translates the typed envelope into the existing call
shape and maps the legacy result back to :class:`HandlerOutcome`.

Frozen-item rejection: if the item is frozen and the caller is
not toggling ``frozen`` itself (and has not opted into ``force``), the
handler short-circuits with ``error.code="frozen"`` before reaching the
mutation layer. The flag is informational at the mutation layer and the
dispatcher needs an explicit refusal to surface it to operators.

Future-concept absorption target: when the execution journal
lands, this handler becomes a journal-emit + ``execute_update`` pair
and the standalone module is absorbed into the journal hot path.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import db_backend
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


class ScalarUpdateRequest(BaseModel):
    """Payload for ``items.scalar.update``.

    ``field`` + ``value`` mirror ``backlog.execute_update`` — single-field
    updates per call. Multi-field PATCH semantics belong on the HTTP
    route; the function call surface is one mutation at a time so the
    dispatcher's event ledger carries one ``YokeFunctionCalled`` per
    field write.
    """

    field: str = Field(..., description="One of mutations.SUPPORTED_UPDATE_FIELDS.")
    value: Any = Field(..., description="New value for the field; type depends on field.")
    done_nonce_verified: bool = False
    force: bool = False
    qa_bypass: bool = False


class ScalarUpdateResponse(BaseModel):
    """Successful result envelope."""

    item_id: int
    field: str
    value: Any
    rework_count: Optional[int] = None
    log: str = ""


# ---------------------------------------------------------------------------
# Error code mapping (mutation layer -> envelope)
# ---------------------------------------------------------------------------


# Mutation-layer ``error_code`` -> dispatcher ``error.code``. Gate codes
# collapse to ``lifecycle_gate_unmet`` across every QA /
# epic-merge / done-ceremony gate; field-validation codes remain
# ``validation_error`` for the route layer to map to HTTP 422.
_GATE_CODES = frozenset({
    "GATE_QA_REVIEWING", "GATE_QA_IMPLEMENTED", "GATE_QA_RELEASE",
    "GATE_QA_DONE", "GATE_EPIC_TASKS", "GATE_EPIC_MERGE", "GATE_DONE_NONCE",
})


def _map_error_code(legacy_code: Optional[str]) -> str:
    if legacy_code and legacy_code in _GATE_CODES:
        return "lifecycle_gate_unmet"
    if legacy_code == "UNSUPPORTED_FIELD":
        return "unsupported_field"
    if legacy_code == "VALIDATION_ERROR":
        return "validation_error"
    return "invalid_payload"


def _error_outcome(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


# ---------------------------------------------------------------------------
# Frozen-item pre-check
# ---------------------------------------------------------------------------


def _frozen_block(item_id: int, payload: ScalarUpdateRequest) -> Optional[HandlerOutcome]:
    """Return an outcome rejecting writes to a frozen item, or None.

    The shared mutation layer treats ``frozen`` as a settable boolean
    rather than a refusal-to-mutate gate. The function-call surface adds
    an explicit refusal so operators see ``error.code="frozen"`` rather
    than discovering a silent post-write side effect.
    """
    if payload.force or payload.field == "frozen":
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
        f"YOK-{item_id} is frozen; thaw the item before updating "
        f"non-frozen fields (or pass force=True for sanctioned overrides).",
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handle_scalar_update(request: FunctionCallRequest) -> HandlerOutcome:
    """Route a typed scalar update through ``backlog.execute_update``."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _error_outcome(
            "invalid_payload",
            "items.scalar.update target must carry kind='item' + item_id.",
        )
    try:
        payload = ScalarUpdateRequest.model_validate(request.payload)
    except Exception as exc:
        return _error_outcome("invalid_payload", f"payload invalid: {exc}")

    blocked = _frozen_block(int(target.item_id), payload)
    if blocked is not None:
        return blocked

    from yoke_core.domain import backlog

    captured = io.StringIO()
    result: Dict[str, Any] = backlog.execute_update(
        item_id=int(target.item_id),
        field=payload.field,
        value=payload.value,
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
            str(result.get("error") or "scalar update failed"),
        )

    response = ScalarUpdateResponse(
        item_id=int(target.item_id),
        field=payload.field,
        value=payload.value,
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
        "function_id": "items.scalar.update",
        "handler": handle_scalar_update,
        "request_model": ScalarUpdateRequest,
        "response_model": ScalarUpdateResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_scalar",
        "target_kinds": ["item"],
        "side_effects": [
            "render_body", "rebuild_board", "github_sync",
            "emit_item_status_changed",
        ],
        "emitted_event_names": [
            "YokeFunctionCalled", "ItemStatusChanged",
        ],
        "guardrails": ["claim_required", "frozen_item_block"],
        "adapter_status": "live",
        "claim_required_kind": "item",
    },
]


__all__ = [
    "handle_scalar_update",
    "ScalarUpdateRequest",
    "ScalarUpdateResponse",
    "REGISTRATIONS",
]
