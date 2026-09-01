"""Installed Yoke project bindings for tenant-fleet database selection.

The generic migration rehearsal domain accepts a caller-supplied fleet.  This
adapter owns Yoke's Platform catalog name and tenant naming convention so tools
shipped in the ``yoke-core`` wheel can select that fleet without importing the
source-checkout-only ``runtime`` package.
"""

from __future__ import annotations

from typing import Callable, List

from yoke_core.domain.pg_test_db_namespace import SCRATCH_DATABASE_PREFIX


PLATFORM_DATABASE = "yoke_platform"
TENANT_DATABASE_PATTERN = "yoke_%"


def database_dsn(authority_dsn: str, database: str) -> str:
    """Retarget an explicit admin authority to one database in its cluster."""
    from psycopg import conninfo

    parameters = conninfo.conninfo_to_dict(authority_dsn)
    return conninfo.make_conninfo(
        **{**parameters, "dbname": database, "connect_timeout": "20"}
    )


def tenant_databases(
    dsn_for: Callable[[str], str],
    *,
    emit: Callable[[str], None] = print,
) -> List[str]:
    """Return Yoke tenant databases, excluding Platform and scratch names.

    The fleet is the set of databases a release must keep serving. A name
    carrying the reserved scratch prefix is not one of them by construction:
    it was created by a test or rehearsal run, it is owned by nothing once
    that run exits, and converging it proves nothing about any tenant. One
    stray was enough to fail a whole fleet rehearsal on a ledger belonging to
    a run that no longer existed, so the exclusion is a contract here rather
    than a filter each caller remembers.

    Counted out loud rather than dropped in silence: a cluster quietly
    accumulating scratch databases is the leak this exclusion makes
    survivable, not a state anyone should stop seeing.
    """
    import psycopg

    with psycopg.connect(dsn_for(PLATFORM_DATABASE), connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datname LIKE %s "
                "ORDER BY datname",
                (TENANT_DATABASE_PATTERN,),
            )
            matched = [
                str(row[0]) for row in cur.fetchall() if row[0] != PLATFORM_DATABASE
            ]

    tenants = [name for name in matched if not name.startswith(SCRATCH_DATABASE_PREFIX)]
    skipped = len(matched) - len(tenants)
    if skipped:
        emit(
            f"scratch databases skipped: {skipped} name(s) carrying the "
            f"reserved {SCRATCH_DATABASE_PREFIX!r} prefix are not fleet "
            "members; remove them with `python3 -m "
            "runtime.api.tools.drop_leftover_test_databases`"
        )
    return tenants


__all__ = [
    "PLATFORM_DATABASE",
    "SCRATCH_DATABASE_PREFIX",
    "TENANT_DATABASE_PATTERN",
    "database_dsn",
    "tenant_databases",
]
