"""Backend-portable row helpers for workflow registry persistence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from yoke_core.domain import db_backend


def marker(conn: Any) -> str:
    """Return the parameter marker accepted by the connection backend."""
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def row_dict(cursor: Any, row: Any) -> Optional[dict]:
    """Convert one mapping or positional database row into a dictionary."""
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    columns = [
        getattr(column, "name", column[0])
        for column in cursor.description
    ]
    return dict(zip(columns, row))


def rows_dict(cursor: Any) -> list[dict]:
    """Convert all remaining database rows into dictionaries."""
    return [
        row
        for raw in cursor.fetchall()
        if (row := row_dict(cursor, raw)) is not None
    ]


__all__ = ["marker", "row_dict", "rows_dict"]
