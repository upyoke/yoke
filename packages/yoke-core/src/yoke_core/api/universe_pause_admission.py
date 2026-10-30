"""Pause admission before authentication can write token-use rows."""

from contextlib import nullcontext

from fastapi.responses import JSONResponse

from yoke_contracts.api_urls import UNIVERSE_EXPORT_PATH
from yoke_contracts.server_mode import SERVER_MODE_ENV, SERVER_MODE_SELF_HOST
from yoke_core.domain import db_backend, universe_source_pause


def install(application):
    @application.middleware("http")
    async def source_pause(request, call_next):
        import os

        if os.environ.get(SERVER_MODE_ENV, "").strip() != SERVER_MODE_SELF_HOST:
            return await call_next(request)
        resume = request.url.path == "/v1/universe/resume" and request.method == "POST"
        # Export retries may use the existing pause; authorization still runs.
        export = (
            request.url.path == UNIVERSE_EXPORT_PATH
            and request.method == "GET"
            and request.query_params.get("pause_source") == "true"
        )
        paused = universe_source_pause.is_paused(db_backend.resolve_pg_dsn())
        if paused and not (resume or export):
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error": {
                        "code": "universe_source_paused",
                        "message": "Source writers are paused for a move; run `yoke universe resume` against this source to restore access.",
                    },
                },
            )
        with universe_source_pause.pause_owner() if resume or export else nullcontext():
            return await call_next(request)
