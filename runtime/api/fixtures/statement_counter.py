"""Count the statements one read issues, without changing what it reads.

A test that cares how much work a read does needs the count, not a
stopwatch: timings drift with the machine, while "one statement per
request" is the property the code is supposed to hold. The wrapper
forwards everything else to the real connection, so the read under test
runs against the same disposable Postgres database as always.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


class CountingConnection:
    """Forward every call to ``inner`` while counting executed statements."""

    def __init__(self, inner: Any) -> None:
        self._conn = inner
        self.statements: Counter[str] = Counter()

    @property
    def count(self) -> int:
        """How many statements ran through this wrapper."""
        return sum(self.statements.values())

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        self.statements[" ".join(str(sql).split())] += 1
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


__all__ = ["CountingConnection"]
