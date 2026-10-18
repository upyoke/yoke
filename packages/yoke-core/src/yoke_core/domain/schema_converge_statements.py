"""Run the additive converge one table at a time, changing only what is missing.

The creation phase runs on every boot and before every release start against
a database that is serving traffic. Two properties keep it from stalling or
deadlocking that traffic:

- **Diff first.** Every statement is read with the Postgres parser and
  checked against the live catalog before it runs
  (:mod:`yoke_core.domain.schema_converge_catalog`). A ``CREATE ... IF NOT
  EXISTS`` whose object exists, an ``ADD COLUMN IF NOT EXISTS`` whose column
  exists, a ``DROP NOT NULL`` on a nullable column, a ``DROP ... IF EXISTS``
  of an absent object, an ``ADD CONSTRAINT`` whose name exists, or a ``CREATE
  OR REPLACE`` function or view whose definition is unchanged is skipped.
  Postgres takes a table's lock before it notices such a statement has
  nothing to do, so skipping it is what lets an already-converged database
  take no table locks at all.
- **One table per transaction.** The open transaction is committed before a
  statement that touches a different table, so a converge transaction never
  holds one table's lock while waiting on another's — the lock-order shape of
  a deadlock against serving requests.

A statement that cannot get its lock (``lock_timeout``) or loses a deadlock
rolls back only that table's open transaction, waits, and replays it. After
:data:`RETRY_DELAYS_SECONDS` it refuses as :data:`LOCK_UNAVAILABLE`, naming
the table. Statement shapes this module does not recognise run unchanged.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from pglast import ast, parse_sql, split
from pglast.enums import ObjectType
from pglast.parser import ParseError
from pglast.visitors import referenced_relations

from yoke_core.domain.schema_converge_catalog import (
    object_name,
    statement_is_satisfied,
)

LOCK_UNAVAILABLE = "schema_converge_lock_unavailable"

#: Waits between attempts at one table's transaction after a lock failure.
RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0)

#: Touch marker for a statement whose tables cannot be read (``DO`` blocks,
#: unparsable text): it always runs in a transaction of its own.
_UNKNOWN = "*"

_PLACEHOLDER = re.compile(r"%\(\w+\)s|%s")


class SchemaConvergeLockError(RuntimeError):
    """One table's converge transaction could not get its locks in budget."""

    def __init__(self, tables: frozenset[str], attempts: int, cause: Exception):
        named = ", ".join(sorted(tables - {_UNKNOWN})) or "an unnamed relation"
        super().__init__(
            f"{LOCK_UNAVAILABLE}: the schema change on {named} could not get "
            f"its table lock after {attempts} attempts ({cause}). Another "
            "transaction is holding it; find the holder with `yoke db read "
            '"SELECT pid, state, query FROM pg_stat_activity WHERE '
            "wait_event_type = 'Lock' OR state = 'idle in transaction'\"`, "
            "let it finish, then rerun the converge."
        )
        self.code = LOCK_UNAVAILABLE
        self.tables = tables


def _is_catalog(name: str) -> bool:
    bare = name.split(".")[-1]
    return bare.startswith("pg_") or name.startswith("information_schema.")


def statement_tables(stmt: Optional[ast.Node]) -> frozenset[str]:
    """Return the user tables *stmt* locks; :data:`_UNKNOWN` when unreadable."""
    if stmt is None or isinstance(stmt, ast.DoStmt):
        return frozenset({_UNKNOWN})
    if isinstance(stmt, ast.DropStmt):
        if stmt.removeType == ObjectType.OBJECT_TRIGGER:
            return frozenset(object_name(obj).rsplit(".", 1)[0] for obj in stmt.objects)
        return frozenset(object_name(obj) for obj in stmt.objects)
    if isinstance(stmt, (ast.CreateFunctionStmt, ast.VariableSetStmt)):
        return frozenset()
    try:
        names = referenced_relations(stmt)
    except Exception:
        return frozenset({_UNKNOWN})
    return frozenset(name for name in names if not _is_catalog(name))


def _parse_one(sql: str) -> Optional[ast.Node]:
    try:
        parsed = parse_sql(_PLACEHOLDER.sub("$1", sql).replace("%%", "%"))
    except ParseError:
        return None
    return parsed[0].stmt if len(parsed) == 1 else None


def _statements(sql: str, params: Any) -> list[str]:
    """Split a parameterless script into statements; a bound query is one."""
    if params is not None:
        return [sql]
    try:
        return list(split(sql)) or [sql]
    except ParseError:
        return [sql]


class ConvergeConnection:
    """A connection whose ``execute`` changes only missing schema, per table.

    Everything else (``cursor``, ``info``, ``transaction`` ...) is the wrapped
    connection's own. ``executed`` records each statement that reached the
    database and ``skipped`` each one the catalog already satisfied.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._held: frozenset[str] = frozenset()
        self._pending: list[tuple[str, Any]] = []
        self.executed: list[str] = []
        self.skipped: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        self._conn.commit()
        self._held, self._pending = frozenset(), []

    def rollback(self) -> None:
        self._conn.rollback()
        self._held, self._pending = frozenset(), []

    def execute(self, sql: Any, params: Any = None, **kwargs: Any) -> Any:
        if not isinstance(sql, str):
            sql = sql.as_string(self._conn)
        cursor = None
        for statement in _statements(sql, params):
            cursor = self._execute_one(statement, params, kwargs)
        return cursor if cursor is not None else self._conn.cursor()

    def _execute_one(self, sql: str, params: Any, kwargs: dict) -> Any:
        stmt = _parse_one(sql)
        tables = statement_tables(stmt)
        isolated = _UNKNOWN in tables or len(tables) > 1
        if self._held and (isolated or not tables <= self._held):
            self.commit()
        if stmt is not None and statement_is_satisfied(self._conn, stmt):
            self.skipped.append(sql)
            if isolated:
                self.commit()
            return None
        self._held |= tables
        cursor = self._run_with_retry(sql, params, kwargs)
        if isolated:
            self.commit()
        return cursor

    def _run_with_retry(self, sql: str, params: Any, kwargs: dict) -> Any:
        import psycopg

        self._pending.append((sql, params))
        batch = self._pending[-1:]
        for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, None), start=1):
            try:
                for pending_sql, pending_params in batch:
                    cursor = self._conn.execute(pending_sql, pending_params, **kwargs)
                self.executed.append(sql)
                return cursor
            except (
                psycopg.errors.LockNotAvailable,
                psycopg.errors.DeadlockDetected,
            ) as exc:
                self._conn.rollback()
                if delay is None:
                    tables, self._held, self._pending = self._held, frozenset(), []
                    raise SchemaConvergeLockError(tables, attempt, exc) from None
                time.sleep(delay)
                # The rollback undid this table's whole open transaction.
                batch = list(self._pending)
        raise AssertionError("unreachable")


@contextmanager
def converging_missing_schema(conn: Any) -> Iterator[ConvergeConnection]:
    """Yield *conn* wrapped so the converge changes only what is missing."""
    guarded = ConvergeConnection(conn)
    try:
        yield guarded
        guarded.commit()
    except BaseException:
        guarded.rollback()
        raise


__all__ = [
    "LOCK_UNAVAILABLE",
    "RETRY_DELAYS_SECONDS",
    "ConvergeConnection",
    "SchemaConvergeLockError",
    "converging_missing_schema",
    "statement_tables",
]
