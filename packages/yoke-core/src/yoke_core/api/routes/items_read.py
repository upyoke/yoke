"""Item read-side route sub-router.

Owns ``GET /items`` (filtered list) and ``GET /items/{item_id}`` (single
item with rendered body).
"""

from __future__ import annotations

from typing import Optional

from fastapi import Query
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain import lifecycle, queries

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


@router.get("/items", response_model=_main.ItemListResponse)
def list_items(
    status: Optional[str] = Query(None, description="Filter by status"),
    project: Optional[str] = Query(None, description="Filter by project"),
    frozen: Optional[bool] = Query(None, description="Filter by frozen flag (true/false)"),
    exclude_done: bool = Query(False, description="Exclude items with status 'done'"),
    exclude_cancelled: bool = Query(False, description="Exclude items with status 'cancelled'"),
    exclude_frozen: bool = Query(False, description="Exclude frozen items"),
) -> _main.ItemListResponse | JSONResponse:
    """List backlog items, optionally filtered by status, project, and queue criteria."""
    if status is not None and not lifecycle.is_valid_item_status(status):
        return _main._error_response(
            400,
            "VALIDATION_ERROR",
            f"Invalid status value '{status}'. "
            f"Must be one of: {', '.join(lifecycle.ALL_ITEM_STATUSES)}",
        )

    item_filter = queries.ItemFilter(
        status=status,
        project=project,
        frozen=frozen,
        exclude_done=exclude_done,
        exclude_cancelled=exclude_cancelled,
        exclude_frozen=exclude_frozen,
    )

    where_clause, params = queries.build_where_clause(
        item_filter, table_prefix="i.",
    )
    sql = (
        "SELECT i.*, p.slug AS project "
        f"FROM items i JOIN projects p ON p.id = i.project_id {where_clause} "
        "ORDER BY i.id"
    )

    conn = _main.get_db_readonly()
    try:
        rows = conn.execute(sql, params).fetchall()
        items = [_main._row_to_item(r, include_body=False) for r in rows]
        return _main.ItemListResponse(items=items, count=len(items))
    finally:
        conn.close()


@router.get("/items/{item_id}", response_model=_main.ItemObject)
def get_item(item_id: int) -> _main.ItemObject | JSONResponse:
    """Get a single item by ID, including its body."""
    conn = _main.get_db_readonly()
    try:
        row = conn.execute(
            "SELECT i.*, p.slug AS project FROM items i "
            "JOIN projects p ON p.id = i.project_id "
            "WHERE i.id = %s",
            (item_id,),
        ).fetchone()
        if row is None:
            return JSONResponse(
                status_code=404,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(
                        code="NOT_FOUND",
                        message=f"Item with id {item_id} not found",
                    )
                ).model_dump(),
            )
        return _main._row_to_item(row, include_body=True)
    finally:
        conn.close()


__all__ = ["router"]
