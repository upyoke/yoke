"""Shared DB connection helpers for Yoke Python engines.

Provides path resolution, connection factory, and query helpers that all
Python modules can import instead of duplicating DB boilerplate.

The retired ``resolve_db_path`` entrypoint is retained only as a guard:
Yoke authority is Postgres, so callers must resolve the active database
through ``YOKE_PG_DSN`` / connected-env binding instead of constructing a
``data/yoke.db`` path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from yoke_core.domain import db_backend

# Retired SQLite compatibility slot retained only for caller signatures.
BUSY_TIMEOUT_MS = 60000


def iso8601_now() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``.

    This is the canonical Yoke timestamp format: sortable, round-trips
    cleanly through ``datetime.fromisoformat`` after ``Z → +00:00``
    normalization, and matches the on-disk format every pre-existing caller
    already produces. Use this helper anywhere a table's ``created_at`` /
    ``updated_at`` column used to rely on a SQLite-side UTC timestamp
    default. The default is being dropped for Postgres portability, so
    callers must supply the value at INSERT time.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_db_path() -> str:
    """Refuse retired SQLite DB-path authority."""
    raise RuntimeError(
        "SQLite authority retired/guarded: Postgres authority selects "
        "the Yoke DB through YOKE_PG_DSN, not a yoke.db path."
    )


def connect(
    path: Optional[str] = None,
    busy_timeout_ms: int = BUSY_TIMEOUT_MS,
) -> Any:
    """Return a connection for the active Yoke authority.

    Features:
    - native psycopg connection semantics.
    - dict-like row access through psycopg ``dict_row``.
    - compatibility slots for legacy callers that still pass a path or timeout.

    Parameters
    ----------
    path:
        Retired path token accepted for legacy callers; ignored by Postgres.
    busy_timeout_ms:
        Retired timeout slot accepted for legacy callers.
    """
    from yoke_core.domain import db_backend

    return db_backend.connect(path, busy_timeout_ms=busy_timeout_ms)


def query_rows(
    conn: Any,
    sql: str,
    params: tuple = (),
) -> List[Any]:
    """Execute *sql* and return all rows."""
    cur = conn.execute(sql, params)
    return cur.fetchall()


def query_one(
    conn: Any,
    sql: str,
    params: tuple = (),
) -> Optional[Any]:
    """Execute *sql* and return the first row, or ``None``."""
    cur = conn.execute(sql, params)
    return cur.fetchone()


def query_scalar(
    conn: Any,
    sql: str,
    params: tuple = (),
) -> Any:
    """Execute *sql* and return the first column of the first row.

    Returns ``None`` if no rows match.
    """
    row = query_one(conn, sql, params)
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]
