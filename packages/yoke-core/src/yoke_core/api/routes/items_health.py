"""Health endpoint sub-router."""

from __future__ import annotations

import os
import time
from typing import List, Tuple

from fastapi.routing import APIRouter

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main
from yoke_contracts.api_urls import API_VERSION_PREFIX
from yoke_contracts.engine_version import advertised_engine_version
from yoke_core.domain import runtime_settings
from yoke_core.domain.github_app_public_runtime import (
    current_github_app_public_advertisement,
)
from yoke_core.domain.schema_readiness import (
    migration_content_identity_status,
    missing_readiness_tables,
    pending_migration_names,
    stranded_by_applied_migrations,
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
    build = os.environ.get("YOKE_BUILD_SHA", "")
    return _main.HealthResponse(
        status="ok",
        version=API_CONTRACT_VERSION,
        engine_version=advertised_engine_version(build=build),
        build=build,
        schema_ready=schema_ready,
        schema_missing_tables=missing,
        migrations_current=not pending,
        pending_migrations=pending,
        can_serve_this_database=(
            not stranded and content_matches and evidence_ready
        ),
        stranded_by_migrations=stranded,
        migration_content_matches=content_matches,
        migration_content_evidence_ready=evidence_ready,
        migration_content_adoption_required=adoption_required,
        migration_content_mismatches=content_mismatches,
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


#: Machine-config key bounding how stale the migration answer may be.
MIGRATIONS_PROBE_TTL_KEY = "health_migrations_probe_ttl_seconds"
MIGRATIONS_PROBE_TTL_DEFAULT = 30

#: Last migration probe: deadline plus membership, serving, and content state.
#:
#: Deliberately a TTL rather than the positive latch above. That latch is
#: justified by "a schema surface cannot lose tables under a running process",
#: which is true of additive convergence and false of a ledger: a restore to an
#: earlier snapshot, a replica failover, or a repointed DSN all move it
#: backwards, and a latched ``True`` would then report a state the database
#: left. Bounding staleness instead keeps the connection cost that motivated
#: the latch — one probe per window, not one per liveness poll — without
#: promising something the underlying fact cannot keep.
_migrations_probe: Tuple[
    float, List[str], List[str], bool, bool, List[str], List[str]
] = (
    0.0,
    [],
    [],
    False,
    False,
    [],
    ["migration content identity has not been probed"],
)


def reset_schema_readiness_cache() -> None:
    """Forget the remembered probe results so the next call probes again."""
    global _schema_confirmed_ready, _migrations_probe
    _schema_confirmed_ready = False
    _migrations_probe = (
        0.0,
        [],
        [],
        False,
        False,
        [],
        ["migration content identity has not been probed"],
    )


def _health_snapshot() -> Tuple[
    bool, List[str], List[str], List[str], bool, bool, List[str], List[str]
]:
    """Return schema, migration-membership, serving, and content state.

    ONE connection answers both questions. Container liveness polls this route
    on a short interval, and every connection resets a serverless database's
    idle-pause timer, so opening a second one per probe would defeat the reason
    the readiness latch exists in the first place.

    The two answers cache differently because the underlying facts differ. A
    schema surface cannot lose tables under a running process, so a positive
    readiness answer is latched for the process lifetime. A ledger CAN move
    backwards — a restore to an earlier snapshot, a replica failover, a
    repointed DSN — so the migration answer is only bounded-stale, never
    latched. Negative answers are never cached either way: a process that
    starts ahead of its schema must keep probing until it converges.
    """
    global _schema_confirmed_ready, _migrations_probe

    now = time.monotonic()
    (
        deadline,
        cached_pending,
        cached_stranded,
        cached_content_matches,
        cached_evidence_ready,
        cached_adoption_required,
        cached_content_mismatches,
    ) = _migrations_probe
    migrations_fresh = now < deadline
    if _schema_confirmed_ready and migrations_fresh:
        return (
            True,
            [],
            cached_pending,
            cached_stranded,
            cached_content_matches,
            cached_evidence_ready,
            cached_adoption_required,
            cached_content_mismatches,
        )

    try:
        conn = _main.get_db_readonly()
    except Exception:
        return (
            (
                True,
                [],
                cached_pending,
                cached_stranded,
                cached_content_matches,
                cached_evidence_ready,
                cached_adoption_required,
                cached_content_mismatches,
            )
            if _schema_confirmed_ready
            else (
                False,
                [],
                cached_pending,
                cached_stranded,
                cached_content_matches,
                cached_evidence_ready,
                cached_adoption_required,
                cached_content_mismatches,
            )
        )
    try:
        if _schema_confirmed_ready:
            ready, missing = True, []
        else:
            missing = missing_readiness_tables(conn)
            ready = not missing
            if ready:
                _schema_confirmed_ready = True
        if migrations_fresh:
            pending, stranded = cached_pending, cached_stranded
            content_matches = cached_content_matches
            evidence_ready = cached_evidence_ready
            adoption_required = cached_adoption_required
            content_mismatches = cached_content_mismatches
        else:
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
            stranded = stranded_by_applied_migrations(
                conn,
                advertised_engine_version(),
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
            ttl = runtime_settings.get_seconds(
                MIGRATIONS_PROBE_TTL_KEY, MIGRATIONS_PROBE_TTL_DEFAULT
            )
            _migrations_probe = (
                now + ttl,
                pending,
                stranded,
                content_matches,
                evidence_ready,
                adoption_required,
                content_mismatches,
            )
    except Exception:
        return (
            (
                True,
                [],
                cached_pending,
                cached_stranded,
                cached_content_matches,
                cached_evidence_ready,
                cached_adoption_required,
                cached_content_mismatches,
            )
            if _schema_confirmed_ready
            else (
                False,
                [],
                cached_pending,
                cached_stranded,
                cached_content_matches,
                cached_evidence_ready,
                cached_adoption_required,
                cached_content_mismatches,
            )
        )
    finally:
        conn.close()
    return (
        ready,
        missing,
        pending,
        stranded,
        content_matches,
        evidence_ready,
        adoption_required,
        content_mismatches,
    )


__all__ = ["reset_schema_readiness_cache", "router"]
