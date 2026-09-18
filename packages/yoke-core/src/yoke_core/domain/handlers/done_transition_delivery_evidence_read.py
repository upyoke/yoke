"""Relay the shared delivery-evidence ladder for the done-transition engine.

The ladder itself is :mod:`yoke_core.domain.delivery_evidence_ladder`. It
lives behind a relayed read because its containment rung needs both a
connection and the project's repository comparison source, neither of which
a client on an https control plane has. The engine keeps the verdict
narrative, as it does for every other guard.

``adapter_status='internal'`` — engine glue, never an agent CLI surface.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class DeliveryEvidenceRequest(BaseModel):
    pass


class DeliveryEvidenceResponse(BaseModel):
    """The shared delivery ladder's verdict, relayed to the engine."""

    state: str
    run_id: str = ""
    run_status: str = ""
    source: str = ""
    reason: str = ""
    recovery: str = ""


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    return request.target.item_id


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_delivery_evidence(request: FunctionCallRequest) -> HandlerOutcome:
    """Answer the shared delivery ladder for one item.

    The containment rung needs a connection and a repository comparison
    source, so it is resolved here rather than client-side; the engine keeps
    the verdict narrative as it does for every other guard.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "delivery_evidence requires target.item_id")

    from yoke_core.domain.delivery_evidence_ladder import delivery_evidence

    try:
        with _connect_rw() as conn:
            verdict = delivery_evidence(conn, int(item_id))
    except Exception as exc:  # noqa: BLE001 - surfaced so the guard aborts
        return _err("delivery_evidence_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "state": verdict.state,
            "run_id": verdict.run_id,
            "run_status": verdict.run_status,
            "source": verdict.source,
            "reason": verdict.reason,
            "recovery": verdict.recovery,
        },
        primary_success=True,
    )


__all__ = [
    "DeliveryEvidenceRequest",
    "DeliveryEvidenceResponse",
    "handle_delivery_evidence",
]
