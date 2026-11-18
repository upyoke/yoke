"""Reuse identical SQL reads within one composed fleet report.

Project sections share schema checks, session policy, machine facts and item
identity reads. This wrapper lives for one composition, never across requests;
mutations and transaction ends invalidate all remembered rows. Savepoint
creation and release preserve reads because they change no data.
"""

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from yoke_core.domain.db_row import PostgresRow

_SCALARS = (str, int, float, bytes, Decimal, UUID, date, datetime, time, timedelta, type(None))


def _shareable(rows: list) -> bool:
    """Rows no reader can change: immutable rows holding only scalar values.

    Those are handed out as they are; rows carrying decoded JSON or other
    mutable values are still copied per read, so one reader's edit never
    reaches another. Copying every row on every hit cost more than the reads
    it saved.
    """
    return all(
        isinstance(row, (PostgresRow, tuple))
        and all(isinstance(value, _SCALARS) for value in row)
        for row in rows
    )


class ReadRows:
    def __init__(self, rows: list, description: Any, shareable: bool = False):
        self.rows = list(rows) if shareable else deepcopy(rows)
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
            rows = cursor.fetchall()
            self._reads[key] = (rows, cursor.description, _shareable(rows))
        return ReadRows(*self._reads[key])

    def commit(self):
        self._reads.clear()
        return self._inner.commit()

    def rollback(self):
        self._reads.clear()
        return self._inner.rollback()
