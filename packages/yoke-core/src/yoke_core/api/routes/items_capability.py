"""Project-capability configuration route sub-router.

Owns ``POST /items/{item_id}/capability`` — configures a capability for the
project associated with the item, upserting into ``project_capabilities``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain import db_backend

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@router.post("/items/{item_id}/capability", response_model=_main.CapabilityResponse)
def configure_capability(
    item_id: int, req: _main.CapabilityRequest,
) -> _main.CapabilityResponse | JSONResponse:
    """Configure a capability for the project associated with an item."""
    if not req.type or not req.type.strip():
        return _main._error_response(
            422, "VALIDATION_ERROR",
            "Field 'type' is required",
        )
    if not req.config:
        return _main._error_response(
            422, "VALIDATION_ERROR",
            "Field 'config' must be a non-empty JSON object",
        )

    conn = _main.get_db_readwrite()
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT * FROM items WHERE id = {p}", (item_id,)
        ).fetchone()
        if row is None:
            return _main._error_response(
                404, "NOT_FOUND",
                f"Item with id {item_id} not found",
            )

        project_id = dict(row).get("project_id") or 1
        config_json = json.dumps(req.config)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        existing = conn.execute(
            f"SELECT id FROM project_capabilities WHERE project_id = {p} AND type = {p}",
            (project_id, req.type),
        ).fetchone()

        is_new = existing is None

        if is_new:
            cursor = conn.execute(
                f"""INSERT INTO project_capabilities (project_id, type, settings, created_at)
                   VALUES ({p}, {p}, {p}, {p})
                   RETURNING id""",
                (project_id, req.type, config_json, now),
            )
            cap_id = cursor.fetchone()[0]
        else:
            cap_id = existing["id"]
            conn.execute(
                f"""UPDATE project_capabilities
                   SET settings = {p}, verified_at = NULL
                   WHERE id = {p}""",
                (config_json, cap_id),
            )

        conn.commit()

        cap_row = conn.execute(
            "SELECT pc.*, p.slug AS project FROM project_capabilities pc "
            f"JOIN projects p ON p.id = pc.project_id WHERE pc.id = {p}",
            (cap_id,),
        ).fetchone()
        cap = dict(cap_row)

        response = _main.CapabilityResponse(
            id=cap["id"],
            project=cap["project"],
            type=cap["type"],
            config=json.loads(cap.get("settings") or "{}"),
            verified_at=cap.get("verified_at"),
            created_at=cap["created_at"],
        )

        status_code = 201 if is_new else 200
        return JSONResponse(
            status_code=status_code,
            content=response.model_dump(),
        )
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(
                503, "DB_BUSY",
                "Database is locked. Retry after a short delay.",
            )
        raise
    finally:
        conn.close()


__all__ = ["router"]
