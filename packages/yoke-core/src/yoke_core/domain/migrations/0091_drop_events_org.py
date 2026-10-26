"""Remove the unused organization column from disposable event telemetry.

The serving floor drains builds whose inserts or projections name the column.
Every universe has one organization; project-less reads use the org-admin role.
"""

from typing import Any
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn: Any) -> None:
    if _table_exists(conn, "events") and _column_exists(conn, "events", "org_id"):
        conn.execute("ALTER TABLE events DROP COLUMN org_id")


def invariants(conn: Any) -> None:
    assert not _table_exists(conn, "events") or not _column_exists(
        conn, "events", "org_id"
    ), "events_org_column_remains: boot must converge the event schema before serving"
