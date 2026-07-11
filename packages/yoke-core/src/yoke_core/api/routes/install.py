"""Install-bundle route — ``GET /v1/projects/{project_id}/install-bundle``.

Serves :func:`yoke_core.domain.install_bundle.build_bundle` to
``yoke install`` / ``yoke refresh`` (Project install contract / project install delivery).
Auth is enforced by the app-level bearer-token middleware plus an explicit
``project.install`` grant on the requested project. Authorization completes
before bundle rendering can seed strategy defaults or read bundle content.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain.install_bundle import (
    InstallBundleError,
    ProjectNotFoundError,
    build_bundle,
)
from yoke_core.api.http_auth import require_auth_context
from yoke_core.domain.actor_permissions import (
    PERM_PROJECT_INSTALL,
    PermissionDenied,
    require_permission,
)
from yoke_core.domain.project_identity import resolve_project_id

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


@router.get("/projects/{project_id}/install-bundle")
def get_install_bundle(project_id: int, request: Request) -> JSONResponse:
    """Render the project-local install bundle for ``project_id``.

    Read-write connection: rendering the ``strategy_files`` section
    cold-starts the placeholder strategy rows for a project with zero
    rows (idempotent; established corpora are never touched).
    """
    auth = require_auth_context(request)
    conn = _main.get_db_readwrite()
    try:
        try:
            resolved_project_id = resolve_project_id(conn, project_id)
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
                project_id=resolved_project_id,
                permission_key=PERM_PROJECT_INSTALL,
            )
        except PermissionDenied as exc:
            return JSONResponse(
                status_code=403,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(code="permission_denied", message=str(exc))
                ).model_dump(),
            )
        try:
            bundle = build_bundle(resolved_project_id, conn)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(code="NOT_FOUND", message=str(exc))
                ).model_dump(),
            )
        except InstallBundleError as exc:
            return JSONResponse(
                status_code=500,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(
                        code="INSTALL_BUNDLE_ERROR",
                        message=str(exc),
                    )
                ).model_dump(),
            )
    finally:
        conn.close()
    return JSONResponse(content=bundle)


__all__ = ["router"]
