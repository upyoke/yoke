"""Items roster handler: ``items.list.run``.

Reuses the same filter/projection building blocks as the ``db_router items
list`` operator-debug CLI (:class:`yoke_core.domain.queries.ItemFilter` +
``build_where_clause`` + ``item_project_join_select``). Keyword and
reference matching is a different read — see
:mod:`yoke_core.domain.handlers.items_search`.

Virtual fields (``body``) are rejected — rendering every body server-side
is the wrong shape for a list read; use ``items.get.run`` per item instead.
Carries ``claim_required_kind=None`` (a read).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.items_project_scope import (
    actor_visible_scope,
    ambiguous_project_error,
    resolve_visible_project_id,
)


_DEFAULT_LIST_FIELDS = (
    "id", "title", "status", "priority", "workflow_id", "source",
)


class ItemsListRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    workflow: Optional[str] = None
    frozen: Optional[bool] = None
    blocked: Optional[bool] = None
    project: Optional[str] = None
    fields: List[str] = Field(
        default_factory=list,
        description=(
            "Column projection. Empty -> "
            "id,title,status,priority,workflow_id,source."
        ),
    )
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


class ItemsListResponse(BaseModel):
    rows: List[Dict[str, Any]]
    count: int


def _validated_list_fields(
    requested: List[str],
) -> tuple[List[str], Optional[HandlerOutcome]]:
    from yoke_core.api.service_client_items_parsing import (
        _QI_ALL_FIELDS,
        _QI_VIRTUAL_FIELDS,
    )

    fields = [str(f).strip() for f in requested if str(f).strip()]
    if not fields:
        return list(_DEFAULT_LIST_FIELDS), None
    for field in fields:
        if field in _QI_VIRTUAL_FIELDS:
            return [], HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=(
                        f"virtual field {field!r} is not listable; read it "
                        "per item via items.get.run (yoke items get)"
                    ),
                    jsonpath="$.payload.fields",
                ),
            )
        if field not in _QI_ALL_FIELDS:
            return [], HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=(
                        f"unknown items column {field!r}. Valid: "
                        + ",".join(sorted(_QI_ALL_FIELDS - _QI_VIRTUAL_FIELDS))
                    ),
                    jsonpath="$.payload.fields",
                ),
            )
    return fields, None


def handle_items_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain import queries
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import (
        AmbiguousProjectRefError,
        item_project_join_select,
    )

    payload = request.payload or {}
    explicit_project = payload.get("project") or None
    fields, field_error = _validated_list_fields(
        list(payload.get("fields") or [])
    )
    if field_error is not None:
        return field_error
    limit = payload.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = -1
        if limit < 1 or limit > 1000:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="limit out of bounds (1..1000)",
                    jsonpath="$.payload.limit",
                ),
            )

    def _opt_bool(key: str) -> Optional[bool]:
        value = payload.get(key)
        return None if value is None else bool(value)

    filt = queries.ItemFilter(
        status=payload.get("status") or None,
        priority=payload.get("priority") or None,
        workflow=payload.get("workflow") or None,
        frozen=_opt_bool("frozen"),
        blocked=_opt_bool("blocked"),
        project=None,
    )
    where_clause, params = queries.build_where_clause(filt, table_prefix="i.")
    select_cols, needs_project = item_project_join_select(fields)
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""

    conn = connect()
    try:
        scoped = actor_visible_scope(conn, request)
        if scoped is not None and not scoped:
            rows = []
        else:
            try:
                project_id = resolve_visible_project_id(
                    conn, explicit_project, scoped,
                )
            except AmbiguousProjectRefError as exc:
                return ambiguous_project_error(str(exc), "$.payload.project")
            if explicit_project is not None and project_id is None:
                rows = []
            else:
                if project_id is not None:
                    where_clause, params = _append_project_id(
                        where_clause, params, project_id,
                    )
                where_clause, params = _append_project_visibility(
                    where_clause, params, scoped,
                )
                sql = (
                    f"SELECT {select_cols} FROM items i{join} "
                    f"{where_clause} ORDER BY i.id"
                )
                sql_params: tuple = tuple(params)
                if limit is not None:
                    sql += " LIMIT %s"
                    sql_params = (*sql_params, limit)
                rows = conn.execute(sql, sql_params).fetchall()
    finally:
        conn.close()
    out_rows = [
        {
            field: ("" if value is None else str(value))
            for field, value in zip(fields, tuple(row))
        }
        for row in rows
    ]
    return HandlerOutcome(
        result_payload={"rows": out_rows, "count": len(out_rows)},
        primary_success=True,
    )


def _append_project_visibility(
    where_clause: str,
    params: List[Any],
    visible_project_ids: Optional[set[int]],
) -> tuple[str, List[Any]]:
    if visible_project_ids is None:
        return where_clause, params
    ordered_ids = sorted(visible_project_ids)
    markers = ", ".join("%s" for _ in ordered_ids)
    clause = f"i.project_id IN ({markers})"
    prefix = " AND " if where_clause else "WHERE "
    return where_clause + prefix + clause, [*params, *ordered_ids]


def _append_project_id(
    where_clause: str,
    params: List[Any],
    project_id: int,
) -> tuple[str, List[Any]]:
    prefix = " AND " if where_clause else "WHERE "
    return where_clause + prefix + "i.project_id = %s", [*params, int(project_id)]


__all__ = [
    "ItemsListRequest",
    "ItemsListResponse",
    "handle_items_list",
]
