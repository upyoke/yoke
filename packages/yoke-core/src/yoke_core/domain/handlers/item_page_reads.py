"""Read handlers for the unified Items roster and workflow detail screens."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


#: The paged-roster inputs. Naming any of them selects the paged read; a
#: request naming none of them keeps the uncapped shape every existing
#: caller — the Overview frontier and the CLI adapter — already relies on.
ROSTER_PAGING_FIELDS = (
    "projects", "search", "workflow", "status", "page_size", "cursor",
)

#: Upper bound on one roster page. The page the product asks for is 50; the
#: ceiling exists so a caller cannot turn the paged read back into the
#: full-history transfer it replaced.
MAX_ROSTER_PAGE_SIZE = 200


class ItemsOverviewListRequest(BaseModel):
    project: str | None = None
    projects: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=1000)
    relevance: str | None = None
    search: str | None = None
    workflow: str | None = None
    status: str | None = None
    page_size: int | None = Field(
        default=None, ge=1, le=MAX_ROSTER_PAGE_SIZE,
    )
    cursor: str | None = None


class ItemsOverviewListResponse(BaseModel):
    rows: list[dict[str, Any]]
    count: int
    # Paged reads only. ``count`` stays the number of rows served so every
    # existing reader keeps its meaning; ``match_count`` is the total behind
    # the page, which is what the roster's heading reports.
    match_count: int | None = None
    next_cursor: str | None = None
    filters: dict[str, Any] | None = None


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
    if payload.relevance not in (None, "overview"):
        return _error(
            "payload_invalid",
            "relevance must be 'overview' when present",
            "$.payload.relevance",
        )
    if any(
        getattr(payload, field) is not None for field in ROSTER_PAGING_FIELDS
    ):
        return _handle_paged_roster(request, payload)

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
            **({"relevance": payload.relevance} if payload.relevance else {}),
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


def _handle_paged_roster(
    request: FunctionCallRequest,
    payload: ItemsOverviewListRequest,
) -> HandlerOutcome:
    """Serve one filtered, ordered roster page plus its full match count.

    Authorization is resolved here, in the service layer, and handed down as
    resolved project ids: the roster query is a domain read and must not
    reach back up into this package to scope itself.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.items_project_scope import (
        actor_visible_scope,
        ambiguous_project_error,
        resolve_visible_project_ids,
    )
    from yoke_core.domain.item_overview_read import enrich_item_overview_rows
    from yoke_core.domain.item_roster_read import (
        RosterCursorError,
        read_item_roster,
    )
    from yoke_core.domain.project_identity import AmbiguousProjectRefError

    if payload.relevance is not None:
        return _error(
            "payload_invalid",
            "relevance selects the Overview window and cannot be combined "
            "with the paged Items roster; drop relevance, or drop the paging "
            "inputs to read the unpaged shape",
            "$.payload.relevance",
        )
    if payload.page_size is None:
        return _error(
            "payload_invalid",
            "page_size is required when any of "
            f"{', '.join(ROSTER_PAGING_FIELDS)} is present, so a filtered "
            "read cannot silently return the whole history; pass "
            f"page_size (1..{MAX_ROSTER_PAGE_SIZE})",
            "$.payload.page_size",
        )
    named = payload.projects
    if named is None and payload.project is not None:
        named = [payload.project]

    conn = connect()
    try:
        scoped = actor_visible_scope(conn, request)
        if scoped is not None and not scoped:
            project_ids: list[int] | None = []
        else:
            try:
                project_ids = resolve_visible_project_ids(conn, named, scoped)
            except AmbiguousProjectRefError as exc:
                return ambiguous_project_error(str(exc), "$.payload.projects")
            if project_ids is None and scoped is not None:
                project_ids = sorted(scoped)
        try:
            result = read_item_roster(
                conn,
                project_ids=project_ids,
                search=payload.search,
                workflow=payload.workflow,
                status=payload.status,
                page_size=payload.page_size,
                cursor=payload.cursor,
            )
        except RosterCursorError as exc:
            return _error("payload_invalid", str(exc), "$.payload.cursor")
    finally:
        conn.close()
    rows = enrich_item_overview_rows(result["rows"], compact=True)
    return HandlerOutcome(
        result_payload={
            "rows": rows,
            "count": len(rows),
            "match_count": result["match_count"],
            "next_cursor": result["next_cursor"],
            "filters": result["filters"],
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
    "MAX_ROSTER_PAGE_SIZE",
    "ROSTER_PAGING_FIELDS",
    "ItemDetailGetRequest",
    "ItemDetailGetResponse",
    "ItemsOverviewListRequest",
    "ItemsOverviewListResponse",
    "handle_item_detail_get",
    "handle_items_overview_list",
]
