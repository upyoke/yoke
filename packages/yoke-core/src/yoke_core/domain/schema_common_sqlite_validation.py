"""Generic SQLite validation readers for ``schema_common``.

These helpers are only for non-authority sqlite_file / worktree-local SQLite
validation surfaces. Yoke control-plane schema reads dispatch to Postgres
catalog readers instead.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


def _generic_sqlite_validation_table_info(
    conn: Any, table: str
) -> List[Tuple[Any, ...]]:
    cur = conn.execute(
        'SELECT cid, name, type, "notnull", dflt_value, pk '
        "FROM pragma_table_info(?)",
        (table,),
    )
    return cur.fetchall()


def _generic_sqlite_validation_table_exists(conn: Any, table: str) -> bool:
    cur = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone()[0] > 0


def _generic_sqlite_validation_trigger_exists(conn: Any, trigger: str) -> bool:
    cur = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=?",
        (trigger,),
    )
    return cur.fetchone()[0] > 0


def _generic_sqlite_validation_table_create_sql(
    conn: Any, table: str
) -> Optional[str]:
    cur = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    row = cur.fetchone()
    return str((row[0] if row else "") or "")


def _generic_sqlite_validation_get_tables(conn: Any) -> List[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cur.fetchall()]


def _generic_sqlite_validation_column_exists(
    conn: Any, table: str, column: str
) -> bool:
    return any(
        row[1] == column
        for row in _generic_sqlite_validation_table_info(conn, table)
    )


def _generic_sqlite_validation_column_is_not_null(
    conn: Any, table: str, column: str
) -> bool:
    for row in _generic_sqlite_validation_table_info(conn, table):
        if row[1] == column:
            return bool(row[3])
    return False


def _generic_sqlite_validation_get_columns(conn: Any, table: str) -> List[str]:
    return [row[1] for row in _generic_sqlite_validation_table_info(conn, table)]


def _generic_sqlite_validation_get_columns_with_types(
    conn: Any, table: str
) -> List[Tuple[str, str]]:
    return [
        (row[1], row[2])
        for row in _generic_sqlite_validation_table_info(conn, table)
    ]


def _generic_sqlite_validation_get_column_default(
    conn: Any, table: str, column: str
) -> Optional[str]:
    for row in _generic_sqlite_validation_table_info(conn, table):
        if row[1] == column:
            return row[4]
    return None


def _generic_sqlite_validation_get_indexes(
    conn: Any, table: Optional[str] = None
) -> List[str]:
    if table is None:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
    else:
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name=? ORDER BY name",
            (table,),
        )
    return [row[0] for row in cur.fetchall()]


def _generic_sqlite_validation_check_constraint_defs(
    conn: Any, table: str
) -> List[str]:
    table_sql = _generic_sqlite_validation_table_create_sql(conn, table)
    return [table_sql] if table_sql else []
