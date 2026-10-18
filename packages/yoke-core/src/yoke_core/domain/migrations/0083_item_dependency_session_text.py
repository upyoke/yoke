"""Store the session that authored a dependency edge as text.

``item_dependencies.session_id`` was declared INTEGER while harness session
ids are text, so no write could record its author and every stored value is
NULL. The column converts in place; any integer already stored keeps its
digits as text. A build that predates this entry still serves the converted
table: it writes NULL there and reads the column only as
``CAST(session_id AS TEXT)``.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _connection_is_postgres,
    _get_columns_with_types,
    _table_exists,
)

TABLE = "item_dependencies"
COLUMN = "session_id"
_TEXT_TYPES = frozenset({"text", "character varying", "varchar"})


def _column_type(conn: Any) -> str:
    types = {
        str(name).lower(): str(typ).lower().split("(", 1)[0].strip()
        for name, typ in _get_columns_with_types(conn, TABLE)
    }
    return types.get(COLUMN, "")


def apply(conn: Any) -> None:
    """Convert the column to TEXT unless it already is."""
    if not _table_exists(conn, TABLE) or not _connection_is_postgres(conn):
        return
    if _column_type(conn) in _TEXT_TYPES:
        return
    conn.execute(
        f'ALTER TABLE "{TABLE}" ALTER COLUMN "{COLUMN}" TYPE TEXT '
        f'USING "{COLUMN}"::text'
    )


def invariants(conn: Any) -> None:
    """Prove the column holds text."""
    if not _table_exists(conn, TABLE) or not _connection_is_postgres(conn):
        return
    column_type = _column_type(conn)
    assert column_type in _TEXT_TYPES, (
        f"{TABLE}.{COLUMN} is {column_type or 'missing'}, expected text"
    )


__all__ = ["COLUMN", "TABLE", "apply", "invariants"]
