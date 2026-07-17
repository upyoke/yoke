"""{{project_display_name}} API — FastAPI application."""

import asyncio
import sys
import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure app/ is on sys.path so utils/ imports work
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from api.config import get_settings
from api.routers.auth import router as auth_router
from api.routers.system import router as system_router

logger = logging.getLogger("{{project_name}}.api")

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("{{project_display_name}} API %s starting", VERSION)

    # Set event loop on broadcaster (must happen in async context)
    if hasattr(app.state, "broadcaster"):
        app.state.broadcaster.set_loop(asyncio.get_event_loop())

    yield

    if hasattr(app.state, "task_runner"):
        app.state.task_runner.shutdown()
    logger.info("{{project_display_name}} API shutting down")


def create_app(db_path: Optional[str] = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Override DB path (for testing). Sets APP_DB_PATH env var.
    """
    if db_path:
        os.environ["APP_DB_PATH"] = db_path

    settings = get_settings()

    app = FastAPI(
        title="{{project_display_name}} API",
        version=VERSION,
        lifespan=lifespan,
    )

    # CORS
    origins = [o.strip() for o in settings.cors_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            "%s %s %d %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response

    # Routers
    app.include_router(auth_router)
    app.include_router(system_router)

    # Task runner + SSE broadcaster (created here so tests can access without lifespan)
    from api.tasks.runner import TaskRunner
    from api.tasks.progress import SSEBroadcaster

    app.state.task_runner = TaskRunner()
    app.state.broadcaster = SSEBroadcaster()

    # Health endpoint (no auth)
    @app.get("/api/health")
    async def health():
        db_ok = False
        schema_version = 0
        try:
            from utils.db import get_connection
            conn = get_connection()
            try:
                conn.execute("SELECT 1")
                db_ok = True
                # Check schema_version table if it exists
                try:
                    row = conn.execute(
                        "SELECT MAX(version) as v FROM schema_version"
                    ).fetchone()
                    if row and row["v"] is not None:
                        schema_version = row["v"]
                except Exception:
                    pass  # Table doesn't exist yet (pre-migration)
            finally:
                conn.close()
        except Exception:
            pass

        return {
            "status": "ok",
            "data": {
                "version": VERSION,
                "db_ok": db_ok,
                "schema_version": schema_version,
            },
        }

    return app


# Default app instance for `uvicorn api.main:app`
app = create_app()
