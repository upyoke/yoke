"""Read handlers for the unified Items roster and workflow detail screens."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemsOverviewListRequest(BaseModel):
    project: str | None = None
    limit: int | None = Field(default=None, ge=1, le=1000)


class ItemsOverviewListResponse(BaseModel):
    rows: list[dict[str, Any]]
    count: int


class ItemDetailGetRequest(BaseModel):
    pass


class ItemDetailGetResponse(BaseModel):
    item: dict[str, Any]
    # Operator execution instructions resolved from the item's pinned
    # workflow and project — a separate field, never spliced into item
    # content, so structured-field writes cannot round-trip it back.
    execution_instructions: list[dict[str, Any]]


def _error(code: str, message: str, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_items_overview_list(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "items.overview.list requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = ItemsOverviewListRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", str(exc), "$.payload")

    from yoke_core.domain.handlers.items_listing import handle_items_list
    from yoke_core.domain.item_overview_read import enrich_item_overview_rows

    list_request = request.model_copy(update={
        "function": "items.list.run",
        "payload": {
            "fields": [
                "id", "internal_id", "title", "workflow_id",
                "workflow_version_id", "status", "priority", "frozen",
                "blocked", "blocked_reason", "deployed_to", "merged_at",
                "created_at", "updated_at", "project", "project_id",
                "project_sequence",
            ],
            **({"project": payload.project} if payload.project else {}),
            **({"limit": payload.limit} if payload.limit else {}),
        },
    })
    outcome = handle_items_list(list_request)
    if not outcome.primary_success:
        return outcome
    rows = enrich_item_overview_rows(outcome.result_payload.get("rows") or [])
    return HandlerOutcome(
        result_payload={
            "rows": rows,
            "count": int(outcome.result_payload.get("count") or len(rows)),
        },
        primary_success=True,
    )


def handle_item_detail_get(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return _error(
            "target_invalid",
            "items.detail.get requires a resolved item target",
            "$.target",
        )
    from yoke_core.domain.item_detail_read import get_item_detail

    try:
        item = get_item_detail(int(request.target.item_id))
    except LookupError as exc:
        return _error("not_found", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_execution_instructions import resolve_for_item

    with connect() as conn:
        instructions = resolve_for_item(conn, int(request.target.item_id))
    return HandlerOutcome(
        result_payload={"item": item, "execution_instructions": instructions},
        primary_success=True,
    )


__all__ = [
    "ItemDetailGetRequest",
    "ItemDetailGetResponse",
    "ItemsOverviewListRequest",
    "ItemsOverviewListResponse",
    "handle_item_detail_get",
    "handle_items_overview_list",
]
