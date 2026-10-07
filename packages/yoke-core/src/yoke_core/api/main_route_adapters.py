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
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.public_item_target import public_item_target
from yoke_core.domain.item_ref_resolution import (
    ITEM_REF_NOT_FOUND,
    check_item_ref_shape,
    resolve_item_ref,
)


def _row_to_item(row: Any, include_body: bool = False, *, conn: Any) -> ItemObject:
    """Convert a DB row to an ItemObject."""
    d = dict(row)
    d["public_ref"] = render_item_ref(conn, int(d["id"]))
    check_item_ref_shape(d["public_ref"])
    d["id"] = d["public_ref"]
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


def resolve_http_item(conn: Any, public_ref: str) -> int | JSONResponse:
    """Resolve a complete route selector using the route's owned connection."""
    try:
        public_item_target(public_ref)
        return resolve_item_ref(conn, public_ref)
    except ValueError as exc:
        return _error_response(
            404 if getattr(exc, "code", None) == ITEM_REF_NOT_FOUND else 400,
            "NOT_FOUND"
            if getattr(exc, "code", None) == ITEM_REF_NOT_FOUND
            else "public_item_ref_required",
            f"{exc}. Use the complete public ref (PREFIX-N); read it from the item list.",
        )
