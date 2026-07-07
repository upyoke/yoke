"""Session inventory endpoints — read-only listings.

GETs for sessions, claims-by-session, claim-by-work-unit, and stale sessions.
Tests patch ``yoke_core.api.main.X`` for DB helpers; this module reaches them
via ``_main.X`` attribute lookup at call time.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Query
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain.sessions import (
    find_stale_sessions,
    get_claim_for_work_unit,
    list_claims_for_session,
    list_harness_sessions,
)

router = APIRouter()


def _main_api():
    import yoke_core.api.main as main
    return main


@router.get("/sessions")
def api_list_sessions(
    lane: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    workspace: Optional[str] = Query(None),
) -> JSONResponse:
    """List active sessions with optional filters."""
    _main = _main_api()
    conn = _main.get_db_readonly()
    try:
        harness_sessions = list_harness_sessions(conn, lane=lane, mode=mode, workspace=workspace)
        return JSONResponse(status_code=200, content={"sessions": harness_sessions, "count": len(harness_sessions)})
    finally:
        conn.close()


@router.get("/sessions/{session_id}/claims")
def api_list_session_claims(session_id: str) -> JSONResponse:
    """List active claims for a session."""
    _main = _main_api()
    conn = _main.get_db_readonly()
    try:
        claims = list_claims_for_session(conn, session_id, active_only=True)
        return JSONResponse(status_code=200, content={"claims": claims, "count": len(claims)})
    finally:
        conn.close()


@router.get("/claims/by-work-unit")
def api_get_claim_by_work_unit(
    item_id: Optional[str] = Query(None),
) -> JSONResponse:
    """Look up who currently claims a given work unit."""
    _main = _main_api()
    conn = _main.get_db_readonly()
    try:
        claim = get_claim_for_work_unit(
            conn, item_id=item_id,
        )
        if claim is None:
            return JSONResponse(status_code=200, content={"claim": None})
        return JSONResponse(status_code=200, content={"claim": claim})
    finally:
        conn.close()


@router.get("/sessions/stale")
def api_list_stale_sessions(
    threshold_minutes: int = Query(10),
) -> JSONResponse:
    """List sessions whose heartbeat is older than the threshold."""
    _main = _main_api()
    conn = _main.get_db_readonly()
    try:
        stale = find_stale_sessions(conn, stale_threshold_minutes=threshold_minutes)
        return JSONResponse(status_code=200, content={"sessions": stale, "count": len(stale)})
    finally:
        conn.close()


__all__ = ["router"]
