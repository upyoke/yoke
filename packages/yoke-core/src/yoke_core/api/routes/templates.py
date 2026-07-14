"""Template routes — ``GET /v1/templates`` + ``GET /v1/templates/{name}``.

Serve :func:`yoke_core.domain.template_bundle.list_templates` and
:func:`~yoke_core.domain.template_bundle.build_template_bundle` to
``yoke templates list`` / ``yoke templates fetch``
(Template registry contract / template registry delivery). Auth is enforced by the app-level
bearer-token middleware like every other ``/v1`` route.
"""

from __future__ import annotations

from fastapi import Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_contracts.template_bundle import TEMPLATE_SOURCE_DEV_ADMIN_QUERY_PARAM
from yoke_core.api.http_auth import require_auth_context
from yoke_core.domain.actor_permissions import (
    PERM_ORG_ADMIN,
    PermissionDenied,
)
from yoke_core.domain.control_plane_authority import (
    require_control_plane_permission,
)
from yoke_core.domain.template_bundle import (
    TemplateAccessDeniedError,
    TemplateNotFoundError,
    build_template_bundle,
    list_templates,
)

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


@router.get("/templates")
def get_templates() -> JSONResponse:
    """List the templates served from this env's code tree."""
    return JSONResponse(content={"templates": list_templates()})


@router.get("/templates/{name}")
def get_template_bundle(
    name: str,
    request: Request,
    include_source_dev_admin: bool = Query(
        False,
        alias=TEMPLATE_SOURCE_DEV_ADMIN_QUERY_PARAM,
    ),
) -> JSONResponse:
    """Render the raw-file bundle for one template."""
    if include_source_dev_admin:
        denial = _require_source_dev_admin_template_permission(request)
        if denial is not None:
            return denial
    try:
        bundle = build_template_bundle(
            name,
            include_source_dev_admin=include_source_dev_admin,
        )
    except TemplateNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content=_main.ErrorResponse(
                error=_main.ErrorDetail(code="NOT_FOUND", message=str(exc))
            ).model_dump(),
        )
    except TemplateAccessDeniedError as exc:
        return JSONResponse(
            status_code=403,
            content=_main.ErrorResponse(
                error=_main.ErrorDetail(code="FORBIDDEN", message=str(exc))
            ).model_dump(),
        )
    return JSONResponse(content=bundle)


def _require_source_dev_admin_template_permission(
    request: Request,
) -> JSONResponse | None:
    auth = require_auth_context(request)
    conn = _main.get_db_readonly()
    try:
        try:
            require_control_plane_permission(
                conn,
                actor_id=auth.actor_id,
                permission_key=PERM_ORG_ADMIN,
            )
        except PermissionDenied as exc:
            return JSONResponse(
                status_code=403,
                content=_main.ErrorResponse(
                    error=_main.ErrorDetail(
                        code="permission_denied",
                        message=str(exc),
                    )
                ).model_dump(),
            )
    finally:
        conn.close()
    return None


__all__ = ["router"]
