"""Declared plaintext secret columns that ``db.read.run`` refuses to return.

A result column is matched by the table OID and column number Postgres
reports for it, so aliases and ``SELECT *`` cannot hide a declared column.
"""

from __future__ import annotations

from typing import Any, List

from yoke_core.domain.handlers.db_read_sql import DbReadRefusal


SECRET_COLUMNS = frozenset({("organizations", "events_signing_key")})


def secret_column_refusal(conn: Any, cursor: Any) -> DbReadRefusal | None:
    """Return a refusal when the result includes a declared secret column."""
    result = cursor.pgresult
    returned = {
        (result.ftable(index), result.ftablecol(index)): index
        for index in range(result.nfields)
        if result.ftable(index)
    }
    if not returned:
        return None
    named: List[str] = []
    for table_oid, column_number, table, column in _declared_column_ids(conn):
        if (table_oid, column_number) in returned:
            named.append(f"{table}.{column}")
    if not named:
        return None
    return DbReadRefusal(
        code="db_read_secret_column_refused",
        message=(
            f"The result includes declared secret column(s) {', '.join(sorted(named))}; "
            "db read never returns them. Select the specific columns you need "
            "instead of these (or instead of SELECT *)."
        ),
    )


def _declared_column_ids(conn: Any) -> list[tuple[int, int, str, str]]:
    tables = sorted({table for table, _ in SECRET_COLUMNS})
    rows = conn.execute(
        "SELECT a.attrelid::bigint, a.attnum::int, c.relname::text, a.attname::text "
        "FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
        "WHERE c.relname = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped",
        (tables,),
    ).fetchall()
    return [
        (int(row[0]), int(row[1]), str(row[2]), str(row[3]))
        for row in rows
        if (str(row[2]), str(row[3])) in SECRET_COLUMNS
    ]
