"""Ouroboros entry read handlers.

Wrap the typed row functions in
:mod:`yoke_core.domain.ouroboros_entries` — the same projection the
``db_router ouroboros list-entries`` operator-debug CLI renders (get is
net-new: the operator CLI never grew a per-entry reader). Field-note read
ids reuse these handlers with a category-prefix filter. These ids carry
``claim_required_kind=None`` (reads).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class OuroborosEntryListRequest(BaseModel):
    unreviewed: bool = False
    project: Optional[str] = None
    category_prefix: Optional[str] = None
    limit: Optional[int] = None


class OuroborosEntryListResponse(BaseModel):
    entries: List[Dict[str, Any]]


class OuroborosEntryGetRequest(BaseModel):
    entry_id: int
    category_prefix: Optional[str] = None


class OuroborosEntryGetResponse(BaseModel):
    entry: Dict[str, Any]


def handle_ouroboros_entry_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = payload.get("project")
    raw_limit = payload.get("limit")
    limit: Optional[int] = None
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="limit must be a positive integer",
                    jsonpath="$.payload.limit",
                ),
            )
        if limit <= 0:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="limit must be a positive integer",
                    jsonpath="$.payload.limit",
                ),
            )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_entries import list_entry_rows

    conn = connect()
    try:
        try:
            entries = list_entry_rows(
                conn,
                unreviewed=bool(payload.get("unreviewed", False)),
                project=(str(project) if project else None),
                category_prefix=(
                    str(payload.get("category_prefix"))
                    if payload.get("category_prefix") else None
                ),
                limit=limit,
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
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"entries": entries},
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
