"""Pause admission before authentication can write token-use rows."""

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
        dsn = db_backend.resolve_pg_dsn()
        paused = universe_source_pause.is_paused(dsn)
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
        if resume or export:
            request.state.universe_paused_read = paused
            try:
                with (
                    universe_source_pause.operation(dsn),
                    universe_source_pause.pause_owner(),
                ):
                    universe_source_pause.recover(dsn)
                    return await call_next(request)
            except universe_source_pause.UniversePausedError as exc:
                return JSONResponse(
                    status_code=409,
                    content={
                        "success": False,
                        "error": {
                            "code": str(exc).partition(":")[0],
                            "message": str(exc),
                        },
                    },
                )
        return await call_next(request)
