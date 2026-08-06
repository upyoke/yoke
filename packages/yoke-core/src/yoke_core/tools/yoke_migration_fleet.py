"""Installed Yoke project bindings for tenant-fleet database selection.

The generic migration rehearsal domain accepts a caller-supplied fleet.  This
adapter owns Yoke's Platform catalog name and tenant naming convention so tools
shipped in the ``yoke-core`` wheel can select that fleet without importing the
source-checkout-only ``runtime`` package.
"""

from __future__ import annotations

from typing import Callable, List


PLATFORM_DATABASE = "yoke_platform"
TENANT_DATABASE_PATTERN = "yoke_%"


def database_dsn(authority_dsn: str, database: str) -> str:
    """Retarget an explicit admin authority to one database in its cluster."""
    from psycopg import conninfo

    parameters = conninfo.conninfo_to_dict(authority_dsn)
    return conninfo.make_conninfo(
        **{**parameters, "dbname": database, "connect_timeout": "20"}
    )


def tenant_databases(dsn_for: Callable[[str], str]) -> List[str]:
    """Return Yoke tenant databases, excluding the Platform control plane."""
    import psycopg

    with psycopg.connect(dsn_for(PLATFORM_DATABASE), connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datname LIKE %s "
                "ORDER BY datname",
                (TENANT_DATABASE_PATTERN,),
            )
            return [
                str(row[0]) for row in cur.fetchall() if row[0] != PLATFORM_DATABASE
            ]


__all__ = [
    "PLATFORM_DATABASE",
    "TENANT_DATABASE_PATTERN",
    "database_dsn",
    "tenant_databases",
]
