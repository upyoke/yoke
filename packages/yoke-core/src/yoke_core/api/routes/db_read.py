"""FastAPI route for the raw diagnostic DB read surface."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.api.http_auth import require_auth_context
from yoke_core.api.routes.functions import _status_for_response
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.yoke_function_dispatch import dispatch


router = APIRouter()


@router.post("/db/read")
def read_db(request: Request, payload: Dict[str, Any]) -> JSONResponse:
    """Run a bounded raw diagnostic read through ``db.read.run``."""
    auth = require_auth_context(request)
    response = dispatch(
        {
            "function": DB_READ_FUNCTION_ID,
            "version": "v1",
            "actor": {"actor_id": str(auth.actor_id), "session_id": ""},
            "target": {"kind": "global"},
            "payload": payload,
            "preconditions": {},
            "options": {},
        },
        ambient_session_id="",
    )
    body = response.model_dump()
    return JSONResponse(content=body, status_code=_status_for_response(body))


__all__ = ["router"]
