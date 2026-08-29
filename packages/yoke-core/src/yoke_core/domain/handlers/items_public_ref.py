"""Read handler: map internal ``items.id`` values to public refs.

The CLI print layer calls this so human output can render ``PREFIX-N``
without adding a sibling field to any machine payload. One statement
covers the whole id set via :func:`render_item_refs`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemsPublicRefLookupRequest(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=512)


class ItemsPublicRefLookupResponse(BaseModel):
    refs: dict[str, str]


def handle_items_public_ref_lookup(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="items.public_ref.lookup requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    try:
        payload = ItemsPublicRefLookupRequest.model_validate(request.payload or {})
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    ids = list(dict.fromkeys(int(item_id) for item_id in payload.item_ids if int(item_id) > 0))
    if not ids:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="item_ids must contain at least one positive internal id",
                jsonpath="$.payload.item_ids",
            ),
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_ref_render import render_item_refs

    try:
        with db_helpers.connect() as conn:
            resolved = render_item_refs(conn, ids)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="lookup_failed",
                message=f"public ref lookup failed: {exc}",
                recovery_hint=(
                    "Retry; if it persists, check the control-plane "
                    "connection with `yoke env list`."
                ),
            ),
        )
    refs: dict[str, str] = {
        str(item_id): ref for item_id, ref in resolved.items() if ref
    }
    return HandlerOutcome(result_payload={"refs": refs}, primary_success=True)


__all__ = [
    "ItemsPublicRefLookupRequest",
    "ItemsPublicRefLookupResponse",
    "handle_items_public_ref_lookup",
]
