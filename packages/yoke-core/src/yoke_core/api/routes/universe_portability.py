"""Self-host-only authenticated universe archive download."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRouter
from starlette.background import BackgroundTask

from yoke_contracts.api_urls import UNIVERSE_EXPORT_PATH
from yoke_contracts.server_mode import SERVER_MODE_ENV, SERVER_MODE_SELF_HOST
from yoke_core.api.http_auth import require_auth_context
from yoke_core.domain import db_backend, db_helpers, universe_export
from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN, PermissionDenied
from yoke_core.domain.control_plane_authority import require_control_plane_permission

router = APIRouter()
_ROUTE_PATH = UNIVERSE_EXPORT_PATH.removeprefix("/v1")


@router.get(_ROUTE_PATH)
def download_self_host_universe(
    request: Request,
    exclude_artifacts: bool = False,
    estimate: bool = False,
    pause_source: bool = False,
):
    """Stream one self-host universe archive to an authenticated org admin."""
    if os.environ.get(SERVER_MODE_ENV, "").strip() != SERVER_MODE_SELF_HOST:
        return _error(404, "not_found", "universe export is not available here")
    auth = require_auth_context(request)
    with db_helpers.connect() as conn:
        try:
            require_control_plane_permission(
                conn,
                actor_id=auth.actor_id,
                permission_key=PERM_ORG_ADMIN,
            )
        except PermissionDenied as exc:
            return _error(403, "permission_denied", str(exc))

    if estimate and pause_source:
        return _error(
            400,
            "universe_export_options_invalid",
            "Use --estimate before --pause-source.",
        )
    if estimate:
        from yoke_core.domain.universe_artifact_transfer import estimate_universe

        try:
            return JSONResponse(
                estimate_universe(
                    dsn=db_backend.resolve_pg_dsn(),
                    exclude_artifacts=exclude_artifacts,
                ),
                headers={"Cache-Control": "no-store"},
            )
        except (RuntimeError, OSError, ValueError):
            return _error(
                409,
                "universe_estimate_failed",
                "repair source storage access and retry the estimate",
            )
    directory = Path(tempfile.mkdtemp(prefix="yoke-self-host-export-"))
    directory.chmod(0o700)
    try:
        options = {"exclude_artifacts": True} if exclude_artifacts else {}
        if pause_source:
            options["pause_source"] = True
        report = universe_export.export_universe(
            dsn=db_backend.resolve_pg_dsn(),
            out=str(directory) + os.sep,
            **options,
        )
        artifact = Path(str(report["artifact"]))
        if artifact.parent != directory or not artifact.is_file():
            raise universe_export.UniverseExportError(
                "the server export did not produce its bounded artifact"
            )
    except universe_export.UniverseExportError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        return _error(
            409,
            "universe_export_refused",
            str(exc),
        )
    except (OSError, KeyError, RuntimeError, TypeError, ValueError):
        shutil.rmtree(directory, ignore_errors=True)
        return _error(
            500,
            "universe_export_failed",
            "the self-host universe export failed",
        )

    return FileResponse(
        artifact,
        media_type="application/x-tar",
        filename=artifact.name,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Yoke-Universe-Format": str(report.get("format") or "universe-tar"),
            "X-Yoke-Universe-Org": str(report.get("org") or ""),
            "X-Yoke-Universe-SHA256": str(report.get("sha256") or ""),
        },
        background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
    )


@router.post("/universe/resume")
def resume_self_host_universe(request: Request):
    from yoke_core.domain import universe_source_pause

    if os.environ.get(SERVER_MODE_ENV, "").strip() != SERVER_MODE_SELF_HOST:
        return _error(404, "not_found", "universe resume is not available here")
    auth = require_auth_context(request)
    with universe_source_pause.pause_owner():
        with db_helpers.connect() as conn:
            try:
                require_control_plane_permission(
                    conn, actor_id=auth.actor_id, permission_key=PERM_ORG_ADMIN
                )
            except PermissionDenied as exc:
                return _error(403, "permission_denied", str(exc))
        try:
            return universe_source_pause.resume(db_backend.resolve_pg_dsn())
        except (RuntimeError, OSError):
            return _error(
                409,
                "universe_resume_failed",
                "Check database availability and pause-marker permissions, then retry `yoke universe resume`.",
            )


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": {"code": code, "message": message}},
    )


__all__ = ["router"]
