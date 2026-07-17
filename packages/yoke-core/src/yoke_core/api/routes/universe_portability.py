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
def download_self_host_universe(request: Request):
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

    directory = Path(tempfile.mkdtemp(prefix="yoke-self-host-export-"))
    directory.chmod(0o700)
    try:
        report = universe_export.export_universe(
            dsn=db_backend.resolve_pg_dsn(),
            out=str(directory) + os.sep,
        )
        artifact = Path(str(report["artifact"]))
        if artifact.parent != directory or not artifact.is_file():
            raise universe_export.UniverseExportError(
                "the server export did not produce its bounded artifact"
            )
    except universe_export.UniverseExportError:
        shutil.rmtree(directory, ignore_errors=True)
        return _error(
            409,
            "universe_export_refused",
            "the self-host universe could not be exported safely",
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


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": {"code": code, "message": message}},
    )


__all__ = ["router"]
