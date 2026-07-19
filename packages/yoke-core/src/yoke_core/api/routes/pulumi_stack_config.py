"""Pulumi stack-config route — ``GET /v1/projects/{project}/pulumi-stack-config``.

Serves a secret-free aggregate settings snapshot for bounded project authority
checks that do not need an exact stack program. Exact Pulumi execution uses the
stack-scoped no-store route plus project-owned Pack source. Auth is the
app-level bearer-token middleware plus the dedicated ``project.render.read``
permission; install, onboarding, snapshot-sync, and project-admin authority are
deliberately separate. The exact-stack response can carry encrypted Pulumi
operator state, but never plaintext secrets; AWS authority remains OIDC-scoped.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain.actor_permissions import (
    PERM_PROJECT_RENDER_READ,
    PermissionDenied,
    require_permission,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_renderer_settings_snapshot import (
    ProjectNotFoundError,
    build_pulumi_stack_config,
)
from yoke_core.domain.project_renderer_pulumi_stack_config import (
    PulumiStackConfigError,
    build_pulumi_stack_config as build_scoped_pulumi_stack_config,
)
from yoke_core.api.http_auth import require_auth_context

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


@router.get("/projects/{project}/pulumi-stack-config")
def get_pulumi_stack_config(project: str, request: Request) -> JSONResponse:
    """Serve the stack-config payload for ``project`` (slug or numeric id)."""
    auth = require_auth_context(request)
    conn = _main.get_db_readonly()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError as exc:
            return JSONResponse(
                status_code=404,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(code="NOT_FOUND", message=str(exc))
                ).model_dump(),
            )
        try:
            require_permission(
                conn,
                actor_id=auth.actor_id,
                project_id=project_id,
                permission_key=PERM_PROJECT_RENDER_READ,
            )
        except PermissionDenied as exc:
            return JSONResponse(
                status_code=403,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(code="permission_denied", message=str(exc))
                ).model_dump(),
            )
        try:
            payload = build_pulumi_stack_config(conn, str(project_id))
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(code="NOT_FOUND", message=str(exc))
                ).model_dump(),
            )
    finally:
        conn.close()
    return JSONResponse(content=payload)


@router.get("/projects/{project}/pulumi-stack-config/{stack}")
def get_scoped_pulumi_stack_config(
    project: str, stack: str, request: Request
) -> JSONResponse:
    """Serve sensitive schema-v2 state without the function event ledger."""
    auth = require_auth_context(request)
    conn = _main.get_db_readonly()
    try:
        try:
            project_id = resolve_project_id(conn, project)
            require_permission(
                conn,
                actor_id=auth.actor_id,
                project_id=project_id,
                permission_key=PERM_PROJECT_RENDER_READ,
            )
            payload = build_scoped_pulumi_stack_config(conn, str(project_id), stack)
        except LookupError as exc:
            return _route_error(404, "NOT_FOUND", str(exc))
        except PermissionDenied as exc:
            return _route_error(403, "permission_denied", str(exc))
        except PulumiStackConfigError as exc:
            return _route_error(422, "stack_config_invalid", str(exc))
    finally:
        conn.close()
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "no-store"},
    )


def _route_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=_main.ErrorResponse(
            error=_main.ErrorDetail(code=code, message=message)
        ).model_dump(),
    )


__all__ = ["router"]
