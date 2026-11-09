"""Portable JSON-scope expressions shared by claim indexes and queries."""

from typing import Any

from yoke_core.domain.schema_connection import connection_is_postgres
from yoke_core.domain.sql_json import json_get


def scope_text_sql(conn: Any, column_expr: str, key: str) -> str:
    """Return a portable SQL expression reading one scope value as text."""
    if connection_is_postgres(conn):
        return json_get(column_expr, f"$.{key}")
    return f"json_extract({column_expr}, '$.{key}')"


def scope_int_sql(conn: Any, column_expr: str, key: str) -> str:
    """Return a portable SQL expression reading one scope value as integer."""
    return f"CAST({scope_text_sql(conn, column_expr, key)} AS INTEGER)"


