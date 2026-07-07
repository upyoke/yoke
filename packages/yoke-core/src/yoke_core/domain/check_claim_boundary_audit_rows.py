"""Row access helpers for claim-boundary audit sqlite unit doubles."""

from __future__ import annotations

from typing import Any


class NameIndexRow:
    __slots__ = ("_columns", "_values", "_index")

    def __init__(self, columns: list[str], values: tuple) -> None:
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._index = {name: idx for idx, name in enumerate(columns)}

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def keys(self):
        return self._columns


def ensure_row_factory(conn: Any) -> None:
    from yoke_core.domain import db_backend

    if not db_backend.connection_is_postgres(conn):
        conn.row_factory = lambda cur, row: NameIndexRow(
            [desc[0] for desc in (cur.description or ())], row,
        )


__all__ = ["ensure_row_factory", "NameIndexRow"]
