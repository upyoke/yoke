"""Health endpoint sub-router."""

from __future__ import annotations

import os
import logging
from typing import List, Tuple

from fastapi.routing import APIRouter

from yoke_contracts.github_app_public import GitHubAppUnavailable

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main
from yoke_contracts.api_urls import API_VERSION_PREFIX
from yoke_contracts.engine_version import advertised_engine_version
from yoke_core.domain.github_app_public_runtime import (
    current_github_app_public_advertisement,
)
from yoke_core.domain.schema_readiness import (
    migration_content_identity_status,
    missing_readiness_tables,
    pending_migration_names,
    stranded_by_applied_migrations,
    unreadable_serving_surfaces,
)
from yoke_core.domain.migration_yoke_ledger import (
    yoke_migration_content_schema_is_prepared,
)

router = APIRouter()

#: The API contract version the payload reports — the route-shape token
#: (``v1``), derived from the shared prefix constant so it can never drift
#: from the mounted routes.
API_CONTRACT_VERSION = API_VERSION_PREFIX.strip("/")


@router.get("/health", response_model=_main.HealthResponse)
async def health() -> _main.HealthResponse:
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
    (
        schema_ready,
        missing,
        pending,
        stranded,
        content_matches,
        evidence_ready,
        adoption_required,
        content_mismatches,
    ) = _health_snapshot()
    return _main.HealthResponse(
        status="ok",
        version=API_CONTRACT_VERSION,
        engine_version=_engine_version,
        build=_build,
        schema_ready=schema_ready,
        schema_missing_tables=missing,
        migrations_current=not pending,
        pending_migrations=pending,
        can_serve_this_database=(not stranded and content_matches and evidence_ready),
        stranded_by_migrations=stranded,
        migration_content_matches=content_matches,
        migration_content_evidence_ready=evidence_ready,
        migration_content_adoption_required=adoption_required,
        migration_content_mismatches=content_mismatches,
        github_app=_github_app,
    )


#: Cadence is owned by the lifespan worker, never by an HTTP request.
MIGRATIONS_PROBE_TTL_KEY = "health_migrations_probe_ttl_seconds"
MIGRATIONS_PROBE_TTL_DEFAULT = 30

HealthSnapshot = Tuple[
    bool, List[str], List[str], List[str], bool, bool, List[str], List[str]
]
_UNPROBED: HealthSnapshot = (
    False,
    [],
    ["health_snapshot_pending"],
    [],
    False,
    False,
    [],
    [
        "health_snapshot_pending: background readiness probe has not completed; "
        "retry health after the probe completes and inspect server startup logs"
    ],
)
_snapshot = _UNPROBED
_build = ""
_engine_version = ""
_github_app = GitHubAppUnavailable()
_log = logging.getLogger("yoke.api.health")


def initialize_health_metadata() -> None:
    """Resolve immutable build and startup-attested App metadata once."""
    global _build, _engine_version, _github_app
    _build = os.environ.get("YOKE_BUILD_SHA", "")
    _engine_version = advertised_engine_version(build=_build)
    _github_app = current_github_app_public_advertisement()


def reset_schema_readiness_cache() -> None:
    """Clear the last background probe result between isolated tests."""
    global _snapshot
    _snapshot = _UNPROBED


def _health_snapshot() -> HealthSnapshot:
    """Read the last complete answer without I/O or waiting for a refresh."""
    return _snapshot


def refresh_health_snapshot() -> None:
    """Publish one complete probe atomically; preserve the answer on failure."""
    global _snapshot
    try:
        conn = _main.get_db_readonly()
        try:
            missing = missing_readiness_tables(conn)
            from yoke_core.domain import migrations as migration_history_package
            from yoke_core.domain.migration_history import (
                history_dir,
                ordered_entries,
            )

            history = ordered_entries(history_dir(migration_history_package))
            from yoke_core.domain.migration_yoke_ledger import (
                YOKE_LEDGER_CONTRACT,
            )

            pending = pending_migration_names(conn, history, YOKE_LEDGER_CONTRACT)
            # Same connection and same cadence as the pending probe: both read
            # the ledger, and a second probe would defeat the reason the TTL
            # exists. Both answers also move backwards together — a restore or
            # a repointed DSN changes what was applied and what may serve it.
            # The probe leads: it asks the database whether the shapes this
            # build reads are there, which is true or false independently of
            # any floor an author declared, and a wrong floor is exactly how a
            # fleet once reported itself able to serve a schema it could not.
            stranded = unreadable_serving_surfaces(conn)
            stranded += stranded_by_applied_migrations(
                conn,
                _engine_version,
                history,
                YOKE_LEDGER_CONTRACT,
            )
            try:
                evidence_ready = yoke_migration_content_schema_is_prepared(conn)
            except Exception:  # noqa: BLE001 — public payload stays non-secret
                evidence_ready = False
            try:
                content_status = migration_content_identity_status(
                    conn, history, YOKE_LEDGER_CONTRACT
                )
                content_matches = content_status.content_matches
                adoption_required = list(content_status.adoption_required)
                content_mismatches = [
                    f"{item.entry_name}: recorded digest does not match "
                    "packaged raw migration bytes"
                    for item in content_status.mismatches
                ]
            except Exception:  # noqa: BLE001 — public payload stays non-secret
                content_matches = False
                adoption_required = []
                content_mismatches = ["migration ledger content identity is unreadable"]
            snapshot = (
                not missing,
                missing,
                pending,
                stranded,
                content_matches,
                evidence_ready,
                adoption_required,
                content_mismatches,
            )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — never expose database details publicly
        _log.warning(
            "health_snapshot_refresh_failed: retaining the last complete answer; "
            "check database connectivity and migration readiness, then retry "
            "after the next background refresh"
        )
        return
    _snapshot = snapshot


__all__ = ["reset_schema_readiness_cache", "router"]
