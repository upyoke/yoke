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


class OuroborosEntryListRequest(BaseModel):
    unreviewed: bool = False
    project: Optional[str] = None
    category_prefix: Optional[str] = None
    limit: int = Field(default=DEFAULT_ENTRY_LIST_LIMIT, ge=1, le=MAX_ENTRY_LIST_LIMIT)
    offset: int = Field(default=0, ge=0)
    count: bool = False


class OuroborosEntryListResponse(BaseModel):
    entries: List[Dict[str, Any]] = Field(default_factory=list)
    count: Optional[int] = None
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


def handle_ouroboros_entry_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = payload.get("project")
    limit, offset, limit_error = _validated_limit_offset(payload)
    if limit_error is not None:
        return limit_error
    assert limit is not None and offset is not None

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
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=str(exc),
                    jsonpath="$.payload.project",
                ),
            )
        except ValueError as exc:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=str(exc),
                    jsonpath="$.payload.limit",
                ),
            )
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
