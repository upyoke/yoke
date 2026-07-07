"""Pulumi stack-config route — ``GET /v1/projects/{project}/pulumi-stack-config``.

Serves the renderer-settings snapshot CI consumes via
``render_project <project> --only pulumi --settings-file ...`` so the
Pulumi workflows render stack YAML from DB authority WITHOUT a database
credential (CI OIDC render-auth hardening render-auth hardening). Auth is the app-level
bearer-token middleware plus an explicit ``project.install`` permission
check — the narrowest existing project-scoped grant for serving
project-local rendered files (owner/operator roles carry it; viewer does
not). The payload is deterministic and secret-free; anything secret a
``pulumi up`` needs lives on the OIDC-scoped AWS side, never here.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain.actor_permissions import (
    PERM_PROJECT_INSTALL,
    PermissionDenied,
    require_permission,
)
from yoke_core.domain.project_renderer_settings_snapshot import (
    ProjectNotFoundError,
    build_pulumi_stack_config,
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
            payload = build_pulumi_stack_config(conn, project)
        except ProjectNotFoundError as exc:
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
                project_id=int(payload["project_id"]),
                permission_key=PERM_PROJECT_INSTALL,
            )
        except PermissionDenied as exc:
            return JSONResponse(
                status_code=403,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(
                        code="permission_denied", message=str(exc)
                    )
                ).model_dump(),
            )
    finally:
        conn.close()
    return JSONResponse(content=payload)


__all__ = ["router"]
