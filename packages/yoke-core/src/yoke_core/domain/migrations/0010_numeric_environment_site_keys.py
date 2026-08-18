"""Give sites and environments numeric keys and retain names as vocabulary."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations._numeric_environment_site_keys import (
    DEPENDENT_TABLES,
    rebuild_registry,
    registry_is_numeric,
)
from yoke_core.domain.schema_common import _table_exists


MINIMUM_SERVING_VERSION = "0.1.1+launch.234"


def apply(conn: Any) -> None:
    rebuild_registry(conn)


def invariants(conn: Any) -> None:
    if not registry_is_numeric(conn):
        raise AssertionError("site and environment primary keys are not numeric")
    duplicate_names = conn.execute(
        "SELECT project_id,name,COUNT(*) FROM environments "
        "GROUP BY project_id,name HAVING COUNT(*) > 1"
    ).fetchall()
    if duplicate_names:
        raise AssertionError("environment names are not unique within each project")
    mismatches = conn.execute(
        "SELECT e.id FROM environments e JOIN sites s ON s.id=e.site "
        "WHERE e.project_id <> s.project_id"
    ).fetchall()
    if mismatches:
        raise AssertionError("environment project ownership disagrees with its site")
    for table in DEPENDENT_TABLES:
        if not _table_exists(conn, table):
            continue
        dangling = conn.execute(
            f'SELECT t.target_environment_id FROM "{table}" t '
            "LEFT JOIN environments e ON e.id=t.target_environment_id "
            "WHERE t.target_environment_id IS NOT NULL AND e.id IS NULL"
        ).fetchall()
        if dangling:
            raise AssertionError(f"{table} has dangling environment references")


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
