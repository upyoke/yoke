"""Compatibility route for exposing an item's deployment approval request.

The deployment runner owns stage progression. This route creates or reuses the
current run-stage Inbox decision and reports whether it has been resolved.
"""

from __future__ import annotations

from yoke_contracts.timestamps import format_instant

from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain import db_backend

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main
from yoke_core.api.main_route_adapters import resolve_http_item

router = APIRouter()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@router.post("/items/{public_ref}/approve", response_model=_main.ApproveResponse)
def approve_item(
    public_ref: str, req: _main.ApproveRequest
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
        item_id = resolve_http_item(conn, public_ref)
        if isinstance(item_id, JSONResponse):
            return item_id
        p = _p(conn)
        row = conn.execute(
            f"SELECT id FROM items WHERE id = {p}", (item_id,)
        ).fetchone()
        if row is None:
            return _main._error_response(
                404,
                "NOT_FOUND",
                f"Item {public_ref} not found",
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
                stage=str(active_run["current_stage"] or ""),
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
        if stamp is None or stamp[0] is None:
            return _main._error_response(
                409,
                "APPROVAL_EVIDENCE_UNAVAILABLE",
                "Resolved approval lacks its decision instant; repair the Inbox decision evidence.",
            )
        return _main.ApproveResponse(
            id=public_ref,
            approved_at=format_instant(stamp[0]),
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
