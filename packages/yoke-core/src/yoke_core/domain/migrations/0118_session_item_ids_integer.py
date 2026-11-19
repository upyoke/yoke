"""Retype ``harness_sessions.current_item_id`` and ``recent_item_id`` to INTEGER.

Both columns hold ``items.id`` values but were declared TEXT, so on
Postgres ``JOIN items i ON i.id = hs.current_item_id`` failed with
"operator does not exist: integer = text". A still-TEXT column has its
non-numeric legacy values (``''`` and the May 2026 ``DOCTOR`` /
``STRATEGIZE`` sentinels) nulled, then is cast in place. Fresh installs
already declare INTEGER, so they and replay are a no-op.
"""

from yoke_core.domain.db_backend import connection_is_postgres


MINIMUM_SERVING_VERSION = "next-release"

_COLUMNS = ("current_item_id", "recent_item_id")


def _data_type(conn, column):
    row = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name = 'harness_sessions' AND column_name = %s",
        (column,),
    ).fetchone()
    return None if row is None else str(row[0])


def apply(conn):
    if not connection_is_postgres(conn):
        return
    for column in _COLUMNS:
        if _data_type(conn, column) != "text":
            continue
        conn.execute(
            f"UPDATE harness_sessions SET {column} = NULL "
            f"WHERE {column} IS NOT NULL AND {column} !~ '^[0-9]+$'"
        )
        conn.execute(
            f"ALTER TABLE harness_sessions ALTER COLUMN {column} "
            f"TYPE INTEGER USING {column}::integer"
        )


def invariants(conn):
    if not connection_is_postgres(conn):
        return
    for column in _COLUMNS:
        found = _data_type(conn, column)
        if found != "integer":
            raise AssertionError(
                f"harness_sessions.{column} is {found!r}, expected 'integer'; "
                "rerun migration 0118_session_item_ids_integer"
            )
