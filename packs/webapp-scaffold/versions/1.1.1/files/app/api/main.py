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

from api.config import get_settings  # noqa: E402
from api.routers.auth import router as auth_router  # noqa: E402
from api.routers.system import router as system_router  # noqa: E402

logger = logging.getLogger("{{project_name}}.api")

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("{{project_display_name}} API %s starting", VERSION)

    # Schema convergence is part of boot. Any failed entry or invariant
    # prevents the process from serving behind its own code.
    from db.migrations.migrate import migrate
    result = migrate(running_version=VERSION)
    logger.info(
        "Migration readiness established; restore point: %s",
        result["data"]["restore_point"] or "not needed",
    )

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
        migration = {
            "ledger_ready": False,
            "ready": False,
            "pending": [],
            "unmapped_legacy_versions": [],
            "stranded": [],
        }
        try:
            from utils.db import get_connection
            from db.migrations.migrate import migration_state
            conn = get_connection()
            try:
                conn.execute("SELECT 1")
                db_ok = True
                migration = migration_state(conn, running_version=VERSION)
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

        healthy = db_ok and migration["ready"]
        payload = {
            "status": "ok" if healthy else "error",
            "data": {
                "version": VERSION,
                "db_ok": db_ok,
                "schema_version": schema_version,
                "migrations_current": (
                    migration["ledger_ready"] and not migration["pending"]
                ),
                "migration_ready": migration["ready"],
                "pending_migrations": migration["pending"],
                "unmapped_legacy_versions": migration[
                    "unmapped_legacy_versions"
                ],
                "serving_safe": not migration["stranded"],
                "stranded_migrations": migration["stranded"],
            },
        }
        return JSONResponse(payload, status_code=200 if healthy else 503)

    return app


# Default app instance for `uvicorn api.main:app`
app = create_app()
