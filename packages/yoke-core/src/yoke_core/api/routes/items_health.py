"""Health endpoint sub-router."""

from __future__ import annotations

import os
from typing import List, Tuple

from fastapi.routing import APIRouter

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main
from yoke_contracts.api_urls import API_VERSION_PREFIX
from yoke_contracts.engine_version import advertised_engine_version
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
    )


def _schema_readiness_snapshot() -> Tuple[bool, List[str]]:
    """Probe the readiness table set; an unreachable DB is not ready."""
    try:
        conn = _main.get_db_readonly()
        try:
            missing = missing_readiness_tables(conn)
        finally:
            conn.close()
    except Exception:
        return False, []
    return not missing, missing


__all__ = ["router"]
