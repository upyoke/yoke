"""Store an item dependency's authoring session as that session's own id.

Sessions are identified by text ids, but ``item_dependencies.session_id`` was
born an integer, so no write could record which session authored an edge and
every stored row holds NULL. Builds carrying this entry record the calling
session on each edge they add or change. Any stored value keeps its text form.

An older build still serves against the converted column: it writes NULL
there and reads it only through ``CAST(session_id AS TEXT)``.
"""

from __future__ import annotations

from typing import Any, Optional

TABLE = "item_dependencies"
COLUMN = "session_id"


def _data_type(conn: Any) -> Optional[str]:
    row = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "AND column_name = %s",
        (TABLE, COLUMN),
    ).fetchone()
    return None if row is None else str(row[0])


def apply(conn: Any) -> None:
    """Convert the column to text wherever it is still an integer."""
    if _data_type(conn) in (None, "text"):
        return
    conn.execute(
        f'ALTER TABLE "{TABLE}" ALTER COLUMN "{COLUMN}" TYPE TEXT '
        f'USING "{COLUMN}"::text'
    )


def invariants(conn: Any) -> None:
    """Prove the column holds text wherever the table exists."""
    data_type = _data_type(conn)
    assert data_type in (None, "text"), (
        f"{TABLE}.{COLUMN} must be text after convergence, found {data_type}"
    )


__all__ = ["COLUMN", "TABLE", "apply", "invariants"]
