"""The done-transition's owner delivery notice, sent server-side.

Sending a notice is a control-plane write, and the done-transition engine
runs client-side against an https control plane as readily as a local
Postgres one, so it cannot open a connection to do this itself. This
handler wraps :func:`deployment_delivery_done_notice.notify_delivery_done`
unchanged and returns what delivery did; the engine keeps the closeout
narrative. It is ``adapter_status='internal'`` — engine glue, never an
agent CLI surface — so it carries no CLI adapter row.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class DeliveryDoneNoticeRequest(BaseModel):
    pass


class DeliveryDoneNoticeResponse(BaseModel):
    delivery: str = ""
    run_id: str = ""
    reason: str = ""


def handle_delivery_done_notice(request: FunctionCallRequest) -> HandlerOutcome:
    """Announce a completed delivery to the item's owner, once."""
    if request.target.item_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="delivery_done_notice requires target.item_id",
            ),
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.deployment_delivery_done_notice import (
        notify_delivery_done,
    )

    try:
        with db_helpers.connect() as conn:
            result: dict[str, Any] = notify_delivery_done(
                conn, item_id=int(request.target.item_id)
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - reported, never reverses done
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="delivery_done_notice_failed", message=str(exc)
            ),
        )

    return HandlerOutcome(result_payload=dict(result), primary_success=True)


__all__ = [
    "DeliveryDoneNoticeRequest",
    "DeliveryDoneNoticeResponse",
    "handle_delivery_done_notice",
]
