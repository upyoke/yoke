"""Row shape for psycopg results.

A row-shape adapter, not a connection or SQL dialect facade. It lets callers
migrate off the sqlite-shaped connection bridge without forcing a same-commit
rewrite of every historical ``row[0]`` assertion/helper. Kept beside the
connection factory rather than inside it: the factory decides which database
to open, this decides what its rows look like.
"""

from __future__ import annotations


class PostgresRow:
    """Psycopg row object with name and positional access."""

    __slots__ = ("_columns", "_index", "_values")

    def __init__(self, columns: tuple[str, ...], values: tuple) -> None:
        self._columns = columns
        self._index = {name: i for i, name in enumerate(columns)}
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key) -> bool:
        return key in self._index

    def __eq__(self, other) -> bool:
        if isinstance(other, dict):
            return dict(self.items()) == other
        if isinstance(other, (list, tuple)):
            return self._values == tuple(other)
        return NotImplemented

    def __repr__(self) -> str:
        return repr(dict(self.items()))

    def get(self, key: str, default=None):
        idx = self._index.get(key)
        return default if idx is None else self._values[idx]

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def values(self) -> tuple:
        return self._values

    def items(self):
        return zip(self._columns, self._values)


def postgres_row_factory(cursor):
    """Return a row builder bound to *cursor*'s column names."""
    columns = tuple(desc.name for desc in (cursor.description or ()))

    def make_row(values):
        return PostgresRow(columns, values)

    return make_row


__all__ = ["PostgresRow", "postgres_row_factory"]
