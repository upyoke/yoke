"""Health endpoint sub-router."""

from __future__ import annotations

import os
from typing import List, Tuple

from fastapi.routing import APIRouter

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main
from yoke_contracts.api_urls import API_VERSION_PREFIX
from yoke_contracts.engine_version import advertised_engine_version
from yoke_core.domain.github_app_public_runtime import (
    current_github_app_public_advertisement,
)
from yoke_core.domain.schema_readiness import missing_readiness_tables

router = APIRouter()

#: The API contract version the payload reports — the route-shape token
#: (``v1``), derived from the shared prefix constant so it can never drift
#: from the mounted routes.
API_CONTRACT_VERSION = API_VERSION_PREFIX.strip("/")


@router.get("/health", response_model=_main.HealthResponse)
def health() -> _main.HealthResponse:
    """Return non-sensitive service health.

    ``version`` is the API contract version (route shape), while
    ``engine_version`` is the installed engine distribution's version —
    the skew-handshake value clients compare against their own install.
    ``build`` surfaces the image's baked git sha so deploy gates and
    operators can confirm WHICH code answered, not just that something
    answered. ``schema_ready`` surfaces whether the DB behind the
    service carries the expected schema surface — a live process over
    an uninitialized DB answers 200 here while its data routes fail,
    so deploy gates assert this field rather than liveness alone.
    """
    schema_ready, missing = _schema_readiness_snapshot()
    build = os.environ.get("YOKE_BUILD_SHA", "")
    return _main.HealthResponse(
        status="ok",
        version=API_CONTRACT_VERSION,
        engine_version=advertised_engine_version(build=build),
        build=build,
        schema_ready=schema_ready,
        schema_missing_tables=missing,
        github_app=current_github_app_public_advertisement(),
    )


#: Remembers that this process has observed a complete schema surface.
#: The probe opens a database connection, and container liveness polls this
#: route on a short interval, so probing on every request holds a serverless
#: database permanently awake — each connection resets its idle-pause timer.
#: A schema surface cannot lose tables under a running process, and a deploy
#: replaces the container, so the positive answer is safe to keep for the
#: process lifetime. The negative answer is never cached: a process that
#: starts ahead of its schema must keep probing until it converges.
_schema_confirmed_ready = False


def reset_schema_readiness_cache() -> None:
    """Forget the remembered probe result so the next call probes again."""
    global _schema_confirmed_ready
    _schema_confirmed_ready = False


def _schema_readiness_snapshot() -> Tuple[bool, List[str]]:
    """Probe the readiness table set; an unreachable DB is not ready."""
    global _schema_confirmed_ready
    if _schema_confirmed_ready:
        return True, []
    try:
        conn = _main.get_db_readonly()
        try:
            missing = missing_readiness_tables(conn)
        finally:
            conn.close()
    except Exception:
        return False, []
    if not missing:
        _schema_confirmed_ready = True
    return not missing, missing


__all__ = ["reset_schema_readiness_cache", "router"]
