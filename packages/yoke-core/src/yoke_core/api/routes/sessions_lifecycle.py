"""Session lifecycle endpoints — register, heartbeat, end, reclaim-stale.

Tests patch ``yoke_core.api.main.X`` for DB connection and error helpers; this
module reaches them via ``_main.X`` attribute lookup at call time so the
patches take effect.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Query
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel

from yoke_core.domain import db_backend
from yoke_core.domain.sessions import (
    SessionError,
    clean_stale_harness_sessions,
    end_session,
    heartbeat,
    register_session,
)
from yoke_core.api.routing_config import (
    load_project_routing_settings,
    load_routing_config,
    resolve_execution_lane,
)

router = APIRouter()


def _main_api():
    import yoke_core.api.main as main
    return main


class RegisterSessionRequest(BaseModel):
    """Request body for POST /v1/sessions."""

    session_id: str
    executor: str
    provider: str
    model: str
    execution_lane: str = "primary"
    capabilities: Optional[List[str]] = None
    workspace: str
    project_id: int
    mode: str = "wait"
    offer_envelope: Optional[Dict[str, Any]] = None


@router.post("/sessions")
def api_register_session(req: RegisterSessionRequest) -> JSONResponse:
    """Register a new active session."""
    _main = _main_api()
    conn = _main.get_db_readwrite()
    try:
        execution_lane = req.execution_lane
        project_routing = load_project_routing_settings(conn, req.project_id)
        if project_routing:
            routing_config = load_routing_config(
                _main.get_config_path(),
                project_settings=project_routing,
            )
            execution_lane = resolve_execution_lane(
                executor=req.executor,
                explicit_lane=None,
                routing_config=routing_config,
            )
        result = register_session(
            conn,
            session_id=req.session_id,
            executor=req.executor,
            provider=req.provider,
            model=req.model,
            execution_lane=execution_lane,
            capabilities=req.capabilities,
            workspace=req.workspace,
            project_id=req.project_id,
            mode=req.mode,
            offer_envelope=req.offer_envelope,
        )
        return JSONResponse(status_code=201, content=result)
    except SessionError as e:
        return _main._error_response(409, e.code, e.message)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


@router.post("/sessions/{session_id}/heartbeat")
def api_heartbeat(session_id: str) -> JSONResponse:
    """Update heartbeat for a session and its claims."""
    _main = _main_api()
    conn = _main.get_db_readwrite()
    try:
        result = heartbeat(conn, session_id)
        return JSONResponse(status_code=200, content=result)
    except SessionError as e:
        status = 404 if e.code == "NOT_FOUND" else 409
        return _main._error_response(status, e.code, e.message)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


@router.post("/sessions/{session_id}/end")
def api_end_session(
    session_id: str,
    force: bool = False,
    override_chain_end: bool = False,
    chain_end_rationale: Optional[str] = None,
) -> JSONResponse:
    """Mark a session as ended.

    ``force`` alone no longer bypasses the CHAIN_PENDING
    guard. Pass ``override_chain_end=True`` and a non-empty
    ``chain_end_rationale`` to override; the override is recorded as
    ``ChainDeclineOverridden`` for audit.
    """
    _main = _main_api()
    if override_chain_end and not (chain_end_rationale and chain_end_rationale.strip()):
        return _main._error_response(
            400,
            "OVERRIDE_RATIONALE_REQUIRED",
            "override_chain_end requires a non-empty chain_end_rationale.",
        )
    conn = _main.get_db_readwrite()
    try:
        result = end_session(
            conn,
            session_id,
            force=force,
            override_chain_end=override_chain_end,
            chain_end_rationale=chain_end_rationale,
        )
        return JSONResponse(status_code=200, content=result)
    except SessionError as e:
        if e.code in ("CHAIN_PENDING", "ACTIVE_CLAIM"):
            return _main._error_response(409, e.code, e.message)
        status = 404 if e.code == "NOT_FOUND" else 409
        return _main._error_response(status, e.code, e.message)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


@router.post("/sessions/reclaim-stale")
def api_reclaim_stale(
    threshold_minutes: int = Query(10),
    progress_threshold_minutes: int = Query(90),
) -> JSONResponse:
    """Unified stale-session cleanup."""
    _main = _main_api()
    conn = _main.get_db_readwrite()
    try:
        result = clean_stale_harness_sessions(
            conn,
            stale_threshold_minutes=threshold_minutes,
            progress_threshold_minutes=progress_threshold_minutes,
        )
        return JSONResponse(status_code=200, content=result)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


__all__ = ["router", "RegisterSessionRequest"]
