"""Route adapters shared by the FastAPI modules.

Owns the small adapter functions route handlers reach for via
``import yoke_core.api.main as _main``: the row-to-response converter,
and the standard error JSON envelope. Project scope is
resolved by ``yoke_core.domain.session_project_scope`` upstream of the
route layer.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from yoke_core.api.main_models import ErrorDetail, ErrorResponse, ItemObject


def _row_to_item(row: Any, include_body: bool = False) -> ItemObject:
    """Convert a DB row to an ItemObject."""
    d = dict(row)
    d["frozen"] = bool(d.get("frozen", 0))
    if not include_body:
        d.pop("body", None)
    return ItemObject(**d)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Build a JSONResponse with the nested ErrorResponse envelope."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(code=code, message=message)
        ).model_dump(),
    )
