"""Reuse identical SQL reads within one composed fleet report.

Project sections share schema checks, session policy, machine facts and item
identity reads. This wrapper lives for one composition, never across requests;
mutations and transaction ends invalidate all remembered rows. Savepoint
creation and release preserve reads because they change no data.
"""

from copy import deepcopy
from typing import Any


class ReadRows:
    def __init__(self, rows: list, description: Any):
        self.rows = deepcopy(rows)
        self.description = description
        self.rowcount = len(rows)
        self.position = 0

    def fetchone(self):
        rows = self.fetchmany(1)
        return rows[0] if rows else None

    def fetchmany(self, size=1):
        rows = self.rows[self.position : self.position + size]
        self.position += len(rows)
        return rows

    def fetchall(self):
        return self.fetchmany(len(self.rows))

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


class ReportReadConnection:
    def __init__(self, conn):
        self._inner = conn
        self._reads = {}

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute(self, sql, params=()):
        command = sql.split(None, 1)[0].upper() if sql.strip() else ""
        if command != "SELECT":
            if command not in {"SAVEPOINT", "RELEASE"}:
                self._reads.clear()
            return self._inner.execute(sql, params)
        key = (sql, tuple(params))
        try:
            hash(key)
        except TypeError:
            return self._inner.execute(sql, params)
        if key not in self._reads:
            cursor = self._inner.execute(sql, params)
            self._reads[key] = (cursor.fetchall(), cursor.description)
        return ReadRows(*self._reads[key])

    def commit(self):
        self._reads.clear()
        return self._inner.commit()

    def rollback(self):
        self._reads.clear()
        return self._inner.rollback()
