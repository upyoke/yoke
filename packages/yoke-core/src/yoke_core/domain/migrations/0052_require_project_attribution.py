"""Require explicit project attribution without changing existing rows."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _get_column_default

MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLES = ("items", "release_entries")


def apply(conn: Any) -> None:
    if not connection_is_postgres(conn):
        raise RuntimeError("project_attribution_requires_postgres")
    for table in TABLES:
        if _column_exists(conn, table, "project_id"):
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN project_id DROP DEFAULT")


def invariants(conn: Any) -> None:
    for table in TABLES:
        if _column_exists(conn, table, "project_id"):
            assert _get_column_default(conn, table, "project_id") is None, (
                f"project_attribution_default_remains: {table}.project_id"
            )
