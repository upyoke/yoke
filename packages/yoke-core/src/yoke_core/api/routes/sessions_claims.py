"""Session claim endpoints — claim, release, release-all, handoff.

Tests patch ``yoke_core.api.main.X`` for DB and error helpers; this module
reaches them via ``_main.X`` attribute lookup at call time.
"""

from __future__ import annotations

from typing import Optional

from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel

from yoke_core.domain import db_backend
from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    handoff_claim,
    release_all_claims,
    release_claim,
)

router = APIRouter()


def _main_api():
    import yoke_core.api.main as main
    return main


class ClaimWorkRequest(BaseModel):
    """Request body for POST /v1/sessions/{session_id}/claims."""

    item_id: Optional[str] = None
    claim_type: str = "exclusive"


class ReleaseClaimRequest(BaseModel):
    """Request body for POST /v1/claims/{claim_id}/release."""

    reason: str = "released"


class HandoffClaimRequest(BaseModel):
    """Request body for POST /v1/claims/{claim_id}/handoff."""

    target_session_id: str


@router.post("/sessions/{session_id}/claims")
def api_claim_work(session_id: str, req: ClaimWorkRequest) -> JSONResponse:
    """Claim a work unit for a session."""
    _main = _main_api()
    conn = _main.get_db_readwrite()
    try:
        result = claim_work(
            conn,
            session_id=session_id,
            item_id=req.item_id,
            claim_type=req.claim_type,
        )
        return JSONResponse(status_code=201, content=result)
    except SessionError as e:
        if e.code == "NOT_FOUND":
            status = 404
        elif e.code in ("ALREADY_CLAIMED", "DUPLICATE_CLAIM", "SESSION_ENDED"):
            status = 409
        else:
            status = 422
        return _main._error_response(status, e.code, e.message)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


@router.post("/claims/{claim_id}/release")
def api_release_claim(claim_id: int, req: ReleaseClaimRequest) -> JSONResponse:
    """Release a specific claim."""
    _main = _main_api()
    conn = _main.get_db_readwrite()
    try:
        result = release_claim(conn, claim_id, reason=req.reason)
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


@router.post("/sessions/{session_id}/release-all")
def api_release_all_claims(session_id: str) -> JSONResponse:
    """Release all active claims for a session."""
    _main = _main_api()
    conn = _main.get_db_readwrite()
    try:
        count = release_all_claims(conn, session_id, reason="released")
        return JSONResponse(status_code=200, content={"released_count": count})
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


@router.post("/claims/{claim_id}/handoff")
def api_handoff_claim(claim_id: int, req: HandoffClaimRequest) -> JSONResponse:
    """Transfer a claim from one session to another."""
    _main = _main_api()
    conn = _main.get_db_readwrite()
    try:
        result = handoff_claim(conn, claim_id, req.target_session_id)
        return JSONResponse(status_code=201, content=result)
    except SessionError as e:
        if e.code == "NOT_FOUND":
            status = 404
        elif e.code in ("ALREADY_RELEASED", "SESSION_ENDED"):
            status = 409
        else:
            status = 422
        return _main._error_response(status, e.code, e.message)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


__all__ = [
    "router",
    "ClaimWorkRequest",
    "ReleaseClaimRequest",
    "HandoffClaimRequest",
]
