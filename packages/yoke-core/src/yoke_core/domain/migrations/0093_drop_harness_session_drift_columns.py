"""Remove the two main-drift columns harness sessions no longer record.

The drift advisory that wrote them is gone; ``yoke watch pytest --impacted``
now brings a lane current with its base instead. The serving floor drains
builds whose session reads or writes still name the columns.
"""

from typing import Any
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE

COLUMNS = ("last_seen_main_sha", "last_drift_check_at")


def apply(conn: Any) -> None:
    if not _table_exists(conn, "harness_sessions"):
        return
    for column in COLUMNS:
        if _column_exists(conn, "harness_sessions", column):
            conn.execute(f"ALTER TABLE harness_sessions DROP COLUMN {column}")


def invariants(conn: Any) -> None:
    remaining = [
        column
        for column in COLUMNS
        if _table_exists(conn, "harness_sessions")
        and _column_exists(conn, "harness_sessions", column)
    ]
    assert not remaining, (
        f"harness_session_drift_columns_remain: {remaining}; boot must converge "
        "the session schema before serving"
    )
