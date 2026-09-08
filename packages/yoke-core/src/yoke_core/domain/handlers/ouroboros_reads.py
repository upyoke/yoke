"""Ouroboros entry read handlers.

Wrap the typed row functions in
:mod:`yoke_core.domain.ouroboros_entries` — the same projection the
``db_router ouroboros list-entries`` operator-debug CLI renders (get is
net-new: the operator CLI never grew a per-entry reader). Field-note read
ids reuse these handlers with a category-prefix filter. These ids carry
``claim_required_kind=None`` (reads).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.ouroboros_entries import (
    DEFAULT_ENTRY_LIST_LIMIT,
    MAX_ENTRY_LIST_LIMIT,
)
from yoke_core.domain.ouroboros_entry_roster import (
    RosterCursorError,
    RosterFilterError,
    list_roster_page,
    parse_category_prefix,
    parse_review_state,
    parse_roster_shape,
)


class OuroborosEntryListRequest(BaseModel):
    unreviewed: bool = False
    project: Optional[str] = None
    category_prefix: Optional[str] = None
    review_state: Optional[str] = None
    shape: Optional[str] = None
    cursor: Optional[str] = None
    limit: int = Field(default=DEFAULT_ENTRY_LIST_LIMIT, ge=1, le=MAX_ENTRY_LIST_LIMIT)
    offset: int = Field(default=0, ge=0)
    count: bool = False


class OuroborosEntryListResponse(BaseModel):
    entries: List[Dict[str, Any]] = Field(default_factory=list)
    count: Optional[int] = None
    matching_count: Optional[int] = None
    next_cursor: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = None


class OuroborosEntryGetRequest(BaseModel):
    entry_id: int
    category_prefix: Optional[str] = None


class OuroborosEntryGetResponse(BaseModel):
    entry: Dict[str, Any]


def _validated_limit_offset(
    payload: Dict[str, Any],
) -> Tuple[Optional[int], Optional[int], Optional[HandlerOutcome]]:
    raw_limit = payload.get("limit")
    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_ENTRY_LIST_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return None, None, HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="limit must be a positive integer",
                    jsonpath="$.payload.limit",
                ),
            )
        if limit <= 0 or limit > MAX_ENTRY_LIST_LIMIT:
            return None, None, HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=(
                        "limit must be a positive integer "
                        f"<= {MAX_ENTRY_LIST_LIMIT}"
                    ),
                    jsonpath="$.payload.limit",
                ),
            )

    raw_offset = payload.get("offset")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            return None, None, HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="offset must be an integer >= 0",
                    jsonpath="$.payload.offset",
                ),
            )
        if offset < 0:
            return None, None, HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="offset must be an integer >= 0",
                    jsonpath="$.payload.offset",
                ),
            )
    return limit, offset, None


def _payload_error(message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def _handle_roster_list(
    payload: Dict[str, Any],
    limit: int,
    offset: int,
) -> HandlerOutcome:
    if offset:
        return _payload_error(
            "shape=roster pages by cursor, not offset. "
            "Reload the Ouroboros page to restart paging from the newest match.",
            "$.payload.offset",
        )
    try:
        review_state = parse_review_state(
            payload.get("review_state"),
            unreviewed=bool(payload.get("unreviewed", False)),
        )
        category_prefix = parse_category_prefix(payload.get("category_prefix"))
        project = payload.get("project")
        cursor = payload.get("cursor")
        if cursor is not None and cursor != "" and not isinstance(cursor, str):
            return _payload_error(
                "cursor must be a string. Reload the Ouroboros page to "
                "restart paging from the newest match.",
                "$.payload.cursor",
            )
        from yoke_core.domain.db_helpers import connect

        conn = connect()
        try:
            page = list_roster_page(
                conn,
                project=str(project) if project else "",
                review_state=review_state,
                category_prefix=category_prefix,
                limit=limit,
                cursor=str(cursor) if cursor else None,
            )
        finally:
            conn.close()
    except RosterFilterError as exc:
        return _payload_error(str(exc), exc.jsonpath)
    except RosterCursorError as exc:
        return _payload_error(str(exc), "$.payload.cursor")
    except LookupError as exc:
        return _payload_error(str(exc), "$.payload.project")
    except ValueError as exc:
        return _payload_error(str(exc), "$.payload.limit")
    return HandlerOutcome(
        result_payload={
            "entries": page["entries"],
            "matching_count": page["matching_count"],
            "next_cursor": page["next_cursor"],
            "limit": page["limit"],
        },
        primary_success=True,
    )


def handle_ouroboros_entry_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = payload.get("project")
    limit, offset, limit_error = _validated_limit_offset(payload)
    if limit_error is not None:
        return limit_error
    assert limit is not None and offset is not None
    try:
        roster = parse_roster_shape(payload.get("shape"))
    except RosterFilterError as exc:
        return _payload_error(str(exc), exc.jsonpath)
    if roster:
        return _handle_roster_list(payload, limit, offset)

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_entries import (
        count_entry_rows,
        list_entry_rows,
    )

    filters = dict(
        unreviewed=bool(payload.get("unreviewed", False)),
        project=(str(project) if project else None),
        category_prefix=(
            str(payload.get("category_prefix"))
            if payload.get("category_prefix") else None
        ),
    )
    count_only = bool(payload.get("count", False))
    conn = connect()
    try:
        try:
            if count_only:
                total = count_entry_rows(conn, **filters)
                return HandlerOutcome(
                    result_payload={"entries": [], "count": total},
                    primary_success=True,
                )
            entries = list_entry_rows(
                conn,
                **filters,
                limit=limit,
                offset=offset,
            )
        except LookupError as exc:
            # resolve_project_id raises LookupError for unknown projects.
            return _payload_error(str(exc), "$.payload.project")
        except ValueError as exc:
            return _payload_error(str(exc), "$.payload.limit")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "entries": entries,
            "limit": limit,
            "offset": offset,
        },
        primary_success=True,
    )


def handle_ouroboros_entry_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    raw_id = payload.get("entry_id")
    try:
        entry_id = int(raw_id)
    except (TypeError, ValueError):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="entry_id must be an integer",
                jsonpath="$.payload.entry_id",
            ),
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_entries import get_entry_row

    conn = connect()
    try:
        entry = get_entry_row(conn, entry_id)
    finally:
        conn.close()
    if entry is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=f"ouroboros entry {entry_id} not found",
                jsonpath="$.payload.entry_id",
            ),
        )
    category_prefix = payload.get("category_prefix")
    if category_prefix and not str(entry.get("category", "")).startswith(
        str(category_prefix)
    ):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=f"ouroboros entry {entry_id} not found",
                jsonpath="$.payload.entry_id",
            ),
        )
    return HandlerOutcome(
        result_payload={"entry": entry},
        primary_success=True,
    )


__all__ = [
    "OuroborosEntryListRequest", "OuroborosEntryListResponse",
    "handle_ouroboros_entry_list",
    "OuroborosEntryGetRequest", "OuroborosEntryGetResponse",
    "handle_ouroboros_entry_get",
]
