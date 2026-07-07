"""Items listing/search handlers: items.list.run, items.search.run.

``items.list.run`` reuses the same filter/projection building blocks as
the ``db_router items list`` operator-debug CLI
(:class:`yoke_core.domain.queries.ItemFilter` +
``build_where_clause`` + ``item_project_join_select``).
``items.search.run`` wraps :func:`yoke_core.domain.backlog.dedup_search`
(the keyword reader behind ``db_router items dedup-search``).

Virtual fields (``body``) are rejected for list — rendering every body
server-side is the wrong shape for a list read; use ``items.get.run``
per item instead. Both ids carry ``claim_required_kind=None`` (reads).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.actor_project_visibility import (
    actor_visible_project_ids,
    numeric_actor_id,
)


_DEFAULT_LIST_FIELDS = ("id", "title", "status", "priority", "type", "source")


class ItemsListRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    type: Optional[str] = None
    frozen: Optional[bool] = None
    blocked: Optional[bool] = None
    project: Optional[str] = None
    fields: List[str] = Field(
        default_factory=list,
        description="Column projection. Empty -> id,title,status,priority,type,source.",
    )
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


class ItemsListResponse(BaseModel):
    rows: List[Dict[str, Any]]
    count: int


class ItemsSearchRequest(BaseModel):
    keywords: str
    project: Optional[str] = None


class ItemsSearchResponse(BaseModel):
    matches: List[Dict[str, Any]]


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
        item_type=payload.get("type") or None,
        frozen=_opt_bool("frozen"),
        blocked=_opt_bool("blocked"),
        project=None,
    )
    where_clause, params = queries.build_where_clause(filt, table_prefix="i.")
    select_cols, needs_project = item_project_join_select(fields)
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""

    conn = connect()
    try:
        scoped = _actor_visible_scope(conn, request)
        if scoped is not None and not scoped:
            rows = []
        else:
            try:
                project_id = _resolve_visible_project_id(
                    conn, explicit_project, scoped,
                )
            except AmbiguousProjectRefError as exc:
                return _ambiguous_project_error(str(exc), "$.payload.project")
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


def handle_items_search(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    keywords = payload.get("keywords")
    if not keywords or not str(keywords).strip():
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="keywords is required and must be non-empty",
                jsonpath="$.payload.keywords",
            ),
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import AmbiguousProjectRefError

    conn = connect()
    try:
        scoped = _actor_visible_scope(conn, request)
        explicit_project = payload.get("project") or None
        if scoped is not None and not scoped:
            matches = []
        else:
            try:
                project_id = _resolve_visible_project_id(
                    conn, explicit_project, scoped,
                )
            except AmbiguousProjectRefError as exc:
                return _ambiguous_project_error(str(exc), "$.payload.project")
            if explicit_project is not None and project_id is None:
                matches = []
            else:
                matches = _search_items(
                    conn,
                    str(keywords),
                    project_id=project_id,
                    visible_project_ids=scoped,
                )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"matches": matches},
        primary_success=True,
    )


def _actor_visible_scope(
    conn: Any,
    request: FunctionCallRequest,
) -> Optional[set[int]]:
    actor = request.actor.actor_id if request.actor else None
    return actor_visible_project_ids(conn, numeric_actor_id(actor))


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


def _resolve_visible_project_id(
    conn: Any,
    project: Optional[str],
    visible_project_ids: Optional[set[int]],
) -> Optional[int]:
    if project is None:
        return None
    from yoke_core.domain.project_identity import resolve_project

    ident = resolve_project(
        conn, project, required=False, visible_project_ids=visible_project_ids,
    )
    return None if ident is None else ident.id


def _ambiguous_project_error(message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="ambiguous_project",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def _search_items(
    conn: Any,
    keywords: str,
    *,
    project_id: Optional[int],
    visible_project_ids: Optional[set[int]],
) -> list[dict[str, Any]]:
    if visible_project_ids is not None and not visible_project_ids:
        return []
    pattern = f"%{keywords.lower()}%"
    where = (
        "WHERE (LOWER(title) LIKE %s OR LOWER(spec) LIKE %s "
        "OR LOWER(design_spec) LIKE %s OR LOWER(technical_plan) LIKE %s)"
    )
    params: list[Any] = [pattern, pattern, pattern, pattern]
    if project_id is not None:
        where += " AND project_id = %s"
        params.append(int(project_id))
    if visible_project_ids is not None:
        ordered_ids = sorted(visible_project_ids)
        markers = ", ".join("%s" for _ in ordered_ids)
        where += f" AND project_id IN ({markers})"
        params.extend(ordered_ids)
    rows = conn.execute(
        f"SELECT id, title, status FROM items {where} ORDER BY id",
        tuple(params),
    ).fetchall()
    return [
        {"id": int(row["id"]), "title": row["title"], "status": row["status"]}
        for row in rows
    ]


__all__ = [
    "ItemsListRequest", "ItemsListResponse", "handle_items_list",
    "ItemsSearchRequest", "ItemsSearchResponse", "handle_items_search",
]
