"""Yoke API app factory — extracted from main.py.

Centralizes FastAPI app creation, lifespan management, middleware setup,
and router registration.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from starlette.concurrency import run_in_threadpool

from yoke_contracts.engine_version import (
    ENGINE_VERSION_HEADER,
    UNRESOLVED_SCM_FALLBACK_VERSION,
    advertised_engine_version,
)
from yoke_core.api.http_auth import (
    AUTH_STATE_ATTR,
    LANDING_PATH,
    WEB_AUTH_STATE_ATTR,
    authenticate_request,
    authenticate_web_session,
    is_public_path,
    is_web_session_get_path,
)
from yoke_core.api.observability import (
    REQUEST_ID_HEADER,
    REQUEST_ID_STATE_ATTR,
    configure_observability,
    environment_name,
    new_request_id,
    now_ms,
    record_counter,
    record_histogram,
    record_request_phase,
    request_log_extra,
    request_phases,
    service_name,
)


_http_logger = logging.getLogger("yoke.api.http")
_startup_logger = logging.getLogger("yoke.api.startup")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Registers all route modules under a ``/v1`` prefix and wires up the
    lifespan context manager for DB initialization.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Initialize the backing DB and register all function handlers."""
        # Imported here so the reusable app factory does not depend on the
        # canonical module that imports this factory to publish ``app``.
        from yoke_core.api.main import _ensure_db_initialized

        _ensure_db_initialized()
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.github_app_public_runtime import (
            attest_github_app_runtime_identity_with_hard_deadline,
        )

        register_all_handlers()
        await attest_github_app_runtime_identity_with_hard_deadline()
        yield

    build_sha = os.environ.get("YOKE_BUILD_SHA", "")
    engine_version = advertised_engine_version(build=build_sha)
    application = FastAPI(
        title="Yoke API",
        version=engine_version or UNRESOLVED_SCM_FALLBACK_VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    _obs = configure_observability(
        application,
        log_level=os.environ.get("YOKE_API_LOG_LEVEL", "INFO"),
    )
    # Surface the resolved OTel state in the structured log stream so an
    # operator reading CloudWatch can tell whether traces/metrics actually
    # export (``exporting:otlp``) or are instrumented-but-dropped
    # (``instrumented_no_exporter``) without guessing from env settings.
    _startup_logger.info(
        "observability_configured",
        extra={
            "event_name": "ObservabilityConfigured",
            "event_kind": "system",
            "service": service_name(),
            "environment": environment_name(),
            "context": {
                "structured_logging": _obs.structured_logging,
                "otel_enabled": _obs.otel_enabled,
                "otel_reason": _obs.otel_reason,
            },
        },
    )

    # Advertised once per process: the engine dist version this server runs.
    # Empty (source run without dist metadata) means "do not advertise";
    # clients treat the absent header as handshake-silent.
    @application.middleware("http")
    async def bearer_token_auth(request, call_next):
        request_id = new_request_id(request.headers)
        setattr(request.state, REQUEST_ID_STATE_ATTR, request_id)
        started = time.perf_counter()
        auth_context = None
        response = None
        outcome = "completed"
        try:
            auth_started = time.perf_counter()
            auth_context, denial = await _authenticate(request)
            record_request_phase(request, "auth", now_ms(auth_started))
            if denial is not None:
                response = denial
                outcome = "denied"
            else:
                setattr(request.state, ADMISSION_STATE_ATTR, time.perf_counter())
                response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            if engine_version:
                response.headers[ENGINE_VERSION_HEADER] = engine_version
            return response
        except Exception:
            outcome = "failed"
            raise
        finally:
            status_code = getattr(response, "status_code", 500)
            _log_request(
                request,
                request_id=request_id,
                status_code=status_code,
                duration_ms=now_ms(started),
                auth_context=auth_context,
                outcome=outcome,
            )

    return _include_routes(application)


#: Request-state attribute holding the moment the middleware handed the
#: request downstream, so the route can report how long admission waited.
ADMISSION_STATE_ATTR = "yoke_request_admitted_at"


async def _authenticate(request) -> tuple[Any, JSONResponse | None]:
    """Resolve the request's credential, or return the denial to send back.

    Every branch that reaches a database runs in the same worker-thread pool
    FastAPI already uses for synchronous route handlers. Verification opens a
    connection and writes token-use and audit rows, so calling it inline would
    block the single event loop for the whole round trip and stall every
    other in-flight request behind one slow credential check.

    Returns the verified context (``None`` when the path needs no credential)
    and a denial response, never both.
    """
    path = request.url.path
    if is_public_path(path):
        return None, None
    if is_web_session_get_path(request.method, path):
        # Browser web-session cookie: read-only allowlisted GET surfaces
        # only (see http_auth.WEB_SESSION_GET_PATHS for the CSRF
        # rationale). Writes always take the bearer path.
        web_auth = await run_in_threadpool(authenticate_web_session, request)
        if web_auth is not None:
            setattr(request.state, WEB_AUTH_STATE_ATTR, web_auth)
            return web_auth, None
    if request.method == "GET" and path == LANDING_PATH:
        # Anonymous landing page: renders the signed-out shell. Invalid and
        # absent cookies land here identically, so a probing client learns
        # nothing about session existence.
        return None, None
    auth = await run_in_threadpool(authenticate_request, request)
    if not hasattr(auth, "actor_id"):
        return None, auth
    setattr(request.state, AUTH_STATE_ATTR, auth)
    return auth, None


def mark_request_admission(request: Request) -> None:
    """Record how long the request waited between middleware and its route.

    Registered as a router dependency, so it is scheduled exactly like the
    synchronous endpoints it precedes: a rising ``admission_duration_ms``
    means requests are queueing for a worker thread, which no handler-scoped
    timing can show.
    """
    admitted_at = getattr(request.state, ADMISSION_STATE_ATTR, None)
    if isinstance(admitted_at, float):
        record_request_phase(request, "admission", now_ms(admitted_at))


def _log_request(
    request,
    *,
    request_id: str,
    status_code: int,
    duration_ms: int,
    auth_context,
    outcome: str,
) -> None:
    try:
        phases = request_phases(request)
        extra = request_log_extra(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            environment=environment_name(),
            actor_id=getattr(auth_context, "actor_id", None),
            token_id=getattr(auth_context, "token_id", None),
            outcome=outcome,
            phases=phases,
        )
        level = logging.ERROR if status_code >= 500 else logging.INFO
        _http_logger.log(level, "http_request", extra=extra)
        attributes = {
            "http.method": request.method,
            "http.target": request.url.path,
            "http.status_code": status_code,
            "yoke.outcome": outcome,
        }
        record_counter("yoke.http.requests", attributes=attributes)
        record_histogram(
            "yoke.http.request.duration_ms",
            duration_ms,
            attributes=attributes,
        )
        for phase, phase_duration_ms in phases.items():
            record_histogram(
                f"yoke.http.request.{phase}.duration_ms",
                phase_duration_ms,
                attributes=attributes,
            )
    except Exception:
        return


def _include_routes(application: FastAPI) -> FastAPI:
    """Attach API routers to ``application``."""

    admission = [Depends(mark_request_admission)]
    v1_router = APIRouter(prefix="/v1", dependencies=admission)

    # Import route modules and include their routers
    from yoke_core.api.routes.items import router as items_router
    from yoke_core.api.routes.auth_identity import router as auth_identity_router
    from yoke_core.api.routes.sessions import router as sessions_router
    from yoke_core.api.routes.db_read import router as db_read_router
    from yoke_core.api.routes.deploy import router as deploy_router
    from yoke_core.api.routes.qa import router as qa_router
    from yoke_core.api.routes.functions import router as functions_router
    from yoke_core.api.routes.install import router as install_router
    from yoke_core.api.routes.pulumi_stack_config import (
        router as pulumi_stack_config_router,
    )
    from yoke_core.api.routes.hooks import router as hooks_router
    from yoke_core.api.routes.universe_portability import (
        router as universe_portability_router,
    )
    from yoke_core.api.routes.web_sign_in import (
        landing_router as web_landing_router,
        router as web_sign_in_router,
    )

    v1_router.include_router(items_router)
    v1_router.include_router(auth_identity_router)
    v1_router.include_router(sessions_router)
    v1_router.include_router(db_read_router)
    v1_router.include_router(deploy_router)
    v1_router.include_router(qa_router)
    v1_router.include_router(functions_router)
    v1_router.include_router(install_router)
    v1_router.include_router(pulumi_stack_config_router)
    v1_router.include_router(hooks_router)
    v1_router.include_router(universe_portability_router)
    v1_router.include_router(web_sign_in_router)

    application.include_router(v1_router)
    # The signed-in landing page lives at the site root, outside /v1.
    application.include_router(web_landing_router, dependencies=admission)
    return application
