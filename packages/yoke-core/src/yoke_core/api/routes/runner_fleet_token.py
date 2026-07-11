"""Private-key-free runner-fleet token broker for infrastructure CI."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import ValidationError

from yoke_contracts.runner_fleet_token import (
    RunnerFleetTokenRequest,
    RunnerFleetTokenResponse,
)

from yoke_core.api.http_auth import require_auth_context
import yoke_core.api.main as _main
from yoke_core.domain.actor_permissions import (
    PERM_RUNNER_FLEET_TOKEN_ISSUE,
    PermissionDenied,
    require_permission,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.runner_fleet_token_broker import (
    RunnerFleetAuthorityMismatch,
    RunnerFleetTokenBrokerError,
    issue_runner_fleet_token,
)

router = APIRouter()
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
        content=_main.ErrorResponse(
            error=_main.ErrorDetail(code=code, message=message)
        ).model_dump(),
    )


@router.post("/projects/{project}/runner-fleet-token")
async def post_runner_fleet_token(project: str, request: Request) -> JSONResponse:
    """Return only a short-lived token; App key material stays server-side."""
    auth = require_auth_context(request)
    try:
        payload = RunnerFleetTokenRequest.model_validate(await request.json())
    except (ValidationError, ValueError):
        return _error(422, "invalid_request", "invalid runner-fleet token request")

    conn = _main.get_db_readonly()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError:
            return _error(404, "NOT_FOUND", "project not found")
        try:
            require_permission(
                conn,
                actor_id=auth.actor_id,
                project_id=project_id,
                permission_key=PERM_RUNNER_FLEET_TOKEN_ISSUE,
            )
        except PermissionDenied as exc:
            return _error(403, "permission_denied", str(exc))
        try:
            grant = issue_runner_fleet_token(
                conn,
                project=str(project_id),
                authority_sha256=payload.authority_sha256,
            )
        except RunnerFleetAuthorityMismatch as exc:
            return _error(409, exc.code, str(exc))
        except RunnerFleetTokenBrokerError as exc:
            return _error(409, exc.code, str(exc))
    finally:
        conn.close()
    response = RunnerFleetTokenResponse(
        token=grant.token,
        expires_at=grant.expires_at,
        repository=grant.repository,
    )
    return JSONResponse(
        content=response.model_dump(),
        headers=_NO_STORE_HEADERS,
    )


__all__ = ["router"]
