"""Copy implied delivery custody onto an authored flow column.

Until this entry, whether a flow enrolled carried items was inferred from
``definition_schema_version``. That number names the stage vocabulary.
This entry copies the behavior it happened to imply onto
``takes_delivery_custody`` so later vocabulary edits cannot change
custody.

Idempotent against already-authored values: only NULL rows are filled,
because a v2 flow that already declared no custody is this entry's own
output existing before apply. No surface is removed, so this needs no
serving floor.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_flow_delivery_custody import COLUMN
from yoke_core.domain.deployment_flow_policy import RELEASE_POLICY_SCHEMA_VERSION

TABLE = "deployment_flows"


def apply(conn: Any) -> None:
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    if not _table_exists(conn, TABLE) or not _column_exists(conn, TABLE, COLUMN):
        return
    if not _column_exists(conn, TABLE, "definition_schema_version"):
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE {TABLE} SET {COLUMN} = CASE "
        f"WHEN definition_schema_version >= {marker} THEN 1 ELSE 0 END "
        f"WHERE {COLUMN} IS NULL",
        (RELEASE_POLICY_SCHEMA_VERSION,),
    )
    if db_backend.connection_is_postgres(conn):
        conn.execute(f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET NOT NULL")


def invariants(conn: Any) -> None:
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    if not _table_exists(conn, TABLE):
        return
    if not _column_exists(conn, TABLE, COLUMN):
        raise AssertionError(f"{TABLE}.{COLUMN} is missing")
    row = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE {COLUMN} IS NULL"
    ).fetchone()
    missing = int(row[0] if row is not None else 0)
    if missing:
        raise AssertionError(
            f"{TABLE}.{COLUMN} still has {missing} undeclared row(s)"
        )
