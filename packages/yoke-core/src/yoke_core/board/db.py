"""Board renderer DB access layer."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple

import psycopg

from yoke_core.domain import db_backend


class BoardDB:
    """Single-connection wrapper for board rendering.

    The board renderer reads from Yoke's Postgres authority via
    ``YOKE_PG_DSN``. The optional constructor token is retained for older
    call sites that still pass a fixture token; it does not choose authority.

    Usage::

        with BoardDB() as db:
            rows = db.query("SELECT id, title FROM items WHERE status = 'implementing'")
    """

    def __init__(self, _connection_token: Optional[str] = None) -> None:
        # connect_psycopg returns a raw psycopg connection (BoardDB branches on
        # psycopg.errors.*) but routes through the connected-env readiness layer,
        # so a down local Aurora tunnel is self-healed before the board renders.
        self._conn = db_backend.connect_psycopg()
        self._query_cache: dict[Tuple[str, Optional[Tuple[Any, ...]]], List[Tuple]] = {}
        self._scalar_cache: dict[Tuple[str, Optional[Tuple[Any, ...]]], Any] = {}

    def _execute(self, cur: Any, sql: str, params: Optional[Sequence[Any]]) -> None:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)

    def _cache_key(
        self, sql: str, params: Optional[Sequence[Any]]
    ) -> Optional[Tuple[str, Optional[Tuple[Any, ...]]]]:
        values = tuple(params) if params is not None else None
        key = (sql, values)
        try:
            hash(key)
        except TypeError:
            return None
        return key

    def _clear_cache(self) -> None:
        self._query_cache.clear()
        self._scalar_cache.clear()

    # -- query helpers --------------------------------------------------------

    def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple]:
        """Execute *sql* and return all rows as a list of plain tuples.

        The board renderer's contract is positional tuples, so rows stay plain
        and independent of driver-specific row objects.
        """
        key = self._cache_key(sql, params)
        if key is not None and key in self._query_cache:
            return list(self._query_cache[key])
        with self._conn.cursor() as cur:
            self._execute(cur, sql, params)
            rows = [tuple(row) for row in cur.fetchall()]
        if key is not None:
            self._query_cache[key] = rows
        return list(rows)

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        """Execute *sql* and return the first column of the first row, or None."""
        key = self._cache_key(sql, params)
        if key is not None and key in self._scalar_cache:
            return self._scalar_cache[key]
        with self._conn.cursor() as cur:
            self._execute(cur, sql, params)
            row = cur.fetchone()
        value = row[0] if row else None
        if key is not None:
            self._scalar_cache[key] = value
        return value

    def query_quiet(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]:
        """Like :meth:`query` but returns ``[]`` on missing-relation errors.

        Useful for optional tables (e.g. ``deployment_runs``) that may not
        exist in every database. Postgres aborts the whole transaction on a
        failed statement, so the connection is rolled back before returning
        ``[]`` to keep later reads on the same connection alive.
        """
        try:
            return self.query(sql, params)
        except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn):
            self._conn.rollback()
            rows: List[Tuple] = []
            key = self._cache_key(sql, params)
            if key is not None:
                self._query_cache[key] = rows
            return rows
        except psycopg.Error:
            self._conn.rollback()
            raise

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> None:
        """Execute a write statement for board tests and narrow setup paths."""
        self._clear_cache()
        with self._conn.cursor() as cur:
            self._execute(cur, sql, params)

    def executemany(
        self, sql: str, seq: Iterable[Sequence[Any]]
    ) -> None:
        """Execute one write statement for each parameter sequence."""
        self._clear_cache()
        with self._conn.cursor() as cur:
            cur.executemany(sql, seq)

    def commit(self) -> None:
        """Commit pending setup writes."""
        self._clear_cache()
        self._conn.commit()

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> "BoardDB":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
