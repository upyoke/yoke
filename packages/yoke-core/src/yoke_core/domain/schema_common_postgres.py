"""Postgres catalog readers for ``schema_common``."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


def _row_value(row: Any, key: str, index: int) -> Any:
    """Read either a sequence row or a mapping row."""
    if hasattr(row, "keys"):
        return row[key]
    return row[index]


def _postgres_table_exists(conn: Any, table: str) -> bool:
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class cls
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND cls.relname = %s
              AND cls.relkind IN ('r', 'p')
        )
        """,
        (table,),
    ).fetchone()
    return bool(row and _row_value(row, "exists", 0))


def _postgres_get_tables(conn: Any) -> List[str]:
    cur = conn.execute(
        """
        SELECT cls.relname AS name
        FROM pg_catalog.pg_class cls
        JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = current_schema()
          AND cls.relkind IN ('r', 'p')
        ORDER BY cls.relname
        """
    )
    return [_row_value(row, "name", 0) for row in cur.fetchall()]


def _postgres_column_row(conn: Any, table: str, column: str) -> Optional[Any]:
    return conn.execute(
        """
        SELECT
            att.attname AS name,
            pg_catalog.format_type(att.atttypid, att.atttypmod) AS data_type,
            att.attnotnull AS not_null,
            pg_catalog.pg_get_expr(def.adbin, def.adrelid) AS column_default
        FROM pg_catalog.pg_attribute att
        JOIN pg_catalog.pg_class cls ON cls.oid = att.attrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
        LEFT JOIN pg_catalog.pg_attrdef def
          ON def.adrelid = att.attrelid AND def.adnum = att.attnum
        WHERE ns.nspname = current_schema()
          AND cls.relname = %s
          AND att.attname = %s
          AND att.attnum > 0
          AND NOT att.attisdropped
        """,
        (table, column),
    ).fetchone()


def _postgres_column_exists(conn: Any, table: str, column: str) -> bool:
    return _postgres_column_row(conn, table, column) is not None


def _postgres_column_is_not_null(conn: Any, table: str, column: str) -> bool:
    row = _postgres_column_row(conn, table, column)
    return bool(row) and bool(_row_value(row, "not_null", 2))


def _postgres_get_columns(conn: Any, table: str) -> List[str]:
    cur = conn.execute(
        """
        SELECT att.attname AS name
        FROM pg_catalog.pg_attribute att
        JOIN pg_catalog.pg_class cls ON cls.oid = att.attrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = current_schema()
          AND cls.relname = %s
          AND att.attnum > 0
          AND NOT att.attisdropped
        ORDER BY att.attnum
        """,
        (table,),
    )
    return [_row_value(row, "name", 0) for row in cur.fetchall()]


def _postgres_get_columns_with_types(conn: Any, table: str) -> List[Tuple[str, str]]:
    cur = conn.execute(
        """
        SELECT
            att.attname AS name,
            pg_catalog.format_type(att.atttypid, att.atttypmod) AS data_type
        FROM pg_catalog.pg_attribute att
        JOIN pg_catalog.pg_class cls ON cls.oid = att.attrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = current_schema()
          AND cls.relname = %s
          AND att.attnum > 0
          AND NOT att.attisdropped
        ORDER BY att.attnum
        """,
        (table,),
    )
    return [
        (_row_value(row, "name", 0), _row_value(row, "data_type", 1))
        for row in cur.fetchall()
    ]


def _postgres_get_column_default(
    conn: Any, table: str, column: str
) -> Optional[str]:
    row = _postgres_column_row(conn, table, column)
    return None if row is None else _row_value(row, "column_default", 3)


def _postgres_get_indexes(conn: Any, table: Optional[str] = None) -> List[str]:
    if table is None:
        cur = conn.execute(
            """
            SELECT idx.relname AS name
            FROM pg_catalog.pg_index ind
            JOIN pg_catalog.pg_class idx ON idx.oid = ind.indexrelid
            JOIN pg_catalog.pg_class tbl ON tbl.oid = ind.indrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = tbl.relnamespace
            WHERE ns.nspname = current_schema()
            ORDER BY idx.relname
            """
        )
    else:
        cur = conn.execute(
            """
            SELECT idx.relname AS name
            FROM pg_catalog.pg_index ind
            JOIN pg_catalog.pg_class idx ON idx.oid = ind.indexrelid
            JOIN pg_catalog.pg_class tbl ON tbl.oid = ind.indrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = tbl.relnamespace
            WHERE ns.nspname = current_schema()
              AND tbl.relname = %s
            ORDER BY idx.relname
            """,
            (table,),
        )
    return [_row_value(row, "name", 0) for row in cur.fetchall()]


def _postgres_check_constraint_defs(conn: Any, table: str) -> List[str]:
    rows = conn.execute(
        """
        SELECT pg_catalog.pg_get_constraintdef(con.oid) AS definition
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = current_schema()
          AND cls.relname = %s
          AND con.contype = 'c'
        ORDER BY con.conname
        """,
        (table,),
    ).fetchall()
    return [str(_row_value(row, "definition", 0) or "") for row in rows]
