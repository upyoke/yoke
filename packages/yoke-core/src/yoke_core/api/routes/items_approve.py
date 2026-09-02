"""Compatibility route for exposing an item's deployment approval request.

The deployment runner owns stage progression. This route creates or reuses the
current run-stage Inbox decision and reports whether it has been resolved.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain import db_backend

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@router.post("/items/{item_id}/approve", response_model=_main.ApproveResponse)
def approve_item(
    item_id: int, req: _main.ApproveRequest
) -> _main.ApproveResponse | JSONResponse:
    """Expose the run's Inbox approval without mutating deployment state."""
    if req.comment is not None and len(req.comment) > 500:
        return _main._error_response(
            422,
            "VALIDATION_ERROR",
            "Field 'comment' must be at most 500 characters",
        )

    conn = _main.get_db_readwrite()
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT id FROM items WHERE id = {p}", (item_id,)
        ).fetchone()
        if row is None:
            return _main._error_response(
                404,
                "NOT_FOUND",
                f"Item with id {item_id} not found",
            )

        active_run = conn.execute(
            "SELECT dr.id, dr.current_stage FROM deployment_run_items dri "
            "JOIN deployment_runs dr ON dr.id = dri.run_id "
            f"WHERE dri.item_id = {p} AND dr.status = 'executing' "
            "ORDER BY dr.created_at DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        if active_run is None:
            return _main._error_response(
                409,
                "NO_ACTIVE_RUN",
                "Approval requires an executing deployment run.",
            )
        from yoke_core.domain.deployment_approval_requests import (
            evaluate_deployment_stage_approval,
        )

        try:
            verdict = evaluate_deployment_stage_approval(
                conn,
                run_id=str(active_run["id"]),
            )
        except ValueError as exc:
            return _main._error_response(409, "INVALID_STATE", str(exc))
        if not verdict.satisfied:
            if verdict.resolution_action == "reject":
                return _main._error_response(
                    409,
                    "APPROVAL_REJECTED",
                    f"Inbox decision request {verdict.request_id} was rejected.",
                )
            return _main._error_response(
                409,
                "APPROVAL_REQUIRED",
                f"Resolve Inbox decision request {verdict.request_id} to continue.",
            )
        stamp = conn.execute(
            f"SELECT resolved_at FROM decision_requests WHERE id = {p}",
            (int(verdict.request_id),),
        ).fetchone()
        return _main.ApproveResponse(
            id=item_id,
            approved_at=str(stamp[0] if stamp is not None else ""),
            comment=req.comment,
        )
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(
                503,
                "DB_BUSY",
                "Database is locked. Retry after a short delay.",
            )
        raise
    finally:
        conn.close()


__all__ = ["router"]
