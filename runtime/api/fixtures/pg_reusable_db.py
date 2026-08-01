"""Per-worker reusable test databases with baseline reset between tests.

Database-per-test isolation clones a schema-loaded template for every
test and drops the clone afterwards. Solo, those ``CREATE DATABASE`` /
``DROP DATABASE`` statements are milliseconds; when several suites share
the cluster the per-test file churn saturates disk IO and every suite's
wall clock stretches far past its solo time. This module keeps the
observable isolation contract for the common case while paying the
create/drop cost once per worker process instead of once per test:

- :func:`checkout` lazily builds ONE database per (process, flavor) via
  the caller's ``build`` callable, captures its baseline (schema
  fingerprint, seeded rows, sequence positions), and yields the database
  name for the test to use.
- On checkout exit the database is reset to the captured baseline:
  connections leaked into it are terminated (matching the
  ``DROP DATABASE ... WITH (FORCE)`` semantics of the clone path), every
  user table is cleared server-side without relfilenode churn, seeded
  rows are re-inserted, and sequences are restored.
- A checkout that changed the schema is detected by the fingerprint
  check; the reusable database is discarded and rebuilt on the next
  checkout, so DDL never leaks between tests — schema-mutating tests
  simply keep paying the old one-clone cost.
- Nested checkout of an already-checked-out flavor yields ``None`` so
  the caller falls back to its legacy clone path.

Accepted residual limits: the fingerprint and reset cover
``current_schema()`` only, and database-scoped settings
(``ALTER DATABASE ... SET``) are not reset. Tests needing those
isolations create their own disposable databases.
"""

from __future__ import annotations

import atexit
import contextlib
from typing import Callable, Iterator, Optional

import psycopg

from yoke_core.domain import schema_fingerprint

_STATES: dict[str, dict] = {}


class SchemaDriftDetected(Exception):
    """The checked-out database's schema no longer matches its baseline."""


_USER_TABLES_SQL = """
    SELECT c.oid::regclass::text
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind = 'r'
       AND n.nspname = current_schema()
     ORDER BY 1
"""

_IDENTITY_TABLES_SQL = """
    SELECT DISTINCT a.attrelid::regclass::text
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = current_schema()
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND a.attidentity <> ''
"""

_SEQUENCES_SQL = """
    SELECT c.oid::regclass::text
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind = 'S'
       AND n.nspname = current_schema()
     ORDER BY 1
"""

# DELETE (not TRUNCATE) keeps each table's relfilenode: TRUNCATE assigns a
# fresh storage file to every table and index it touches, which re-creates
# the per-test file churn this module exists to remove.
_CLEAR_TABLES_SQL = """
DO $$
DECLARE rel regclass;
BEGIN
    FOR rel IN
        SELECT c.oid::regclass
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind = 'r'
           AND n.nspname = current_schema()
    LOOP
        EXECUTE format('DELETE FROM %s', rel);
    END LOOP;
END
$$
"""

_TERMINATE_OTHER_BACKENDS_SQL = """
    SELECT pg_terminate_backend(pid)
      FROM pg_stat_activity
     WHERE datname = current_database()
       AND pid <> pg_backend_pid()
"""


def _connect(name: str):
    from runtime.api.fixtures import pg_testdb

    return psycopg.connect(pg_testdb.dsn_for_test_database(name))


def _drop_quietly(name: str) -> None:
    from runtime.api.fixtures import pg_testdb

    try:
        pg_testdb.drop_test_database(name)
    except Exception:
        pass  # cluster startup prune reclaims stragglers


def _capture_baseline(name: str) -> dict:
    """Record everything needed to restore *name* to its just-built state."""
    conn = _connect(name)
    try:
        fingerprint = schema_fingerprint.fingerprint_kind("postgres", conn)
        identity_tables = {
            row[0] for row in conn.execute(_IDENTITY_TABLES_SQL).fetchall()
        }
        rows: list[tuple[str, str, list[str]]] = []
        for (table,) in conn.execute(_USER_TABLES_SQL).fetchall():
            # Composite text form round-trips every column type through the
            # server's own I/O functions, so no client-side type adaptation
            # is needed to re-insert the seed rows at reset time.
            literals = [
                row[0]
                for row in conn.execute(
                    f"SELECT (t.*)::text FROM {table} t"
                ).fetchall()
            ]
            if literals:
                overriding = (
                    "OVERRIDING SYSTEM VALUE " if table in identity_tables else ""
                )
                rows.append((table, overriding, literals))
        sequences: list[tuple[str, int, bool]] = []
        for (seq,) in conn.execute(_SEQUENCES_SQL).fetchall():
            last_value, is_called = conn.execute(
                f"SELECT last_value, is_called FROM {seq}"
            ).fetchone()
            sequences.append((seq, last_value, is_called))
        conn.rollback()
        return {
            "name": name,
            "fingerprint": fingerprint,
            "rows": rows,
            "sequences": sequences,
            "in_use": False,
        }
    finally:
        conn.close()


def _reset(state: dict) -> None:
    """Restore the reusable database to its captured baseline."""
    conn = _connect(state["name"])
    try:
        conn.execute(_TERMINATE_OTHER_BACKENDS_SQL)
        if (
            schema_fingerprint.fingerprint_kind("postgres", conn)
            != state["fingerprint"]
        ):
            raise SchemaDriftDetected(state["name"])
        # Replica role skips FK trigger enforcement so the clear/restore
        # order never has to topologically sort the schema.
        conn.execute("SET session_replication_role = replica")
        conn.execute(_CLEAR_TABLES_SQL)
        for table, overriding, literals in state["rows"]:
            conn.execute(
                f"INSERT INTO {table} {overriding}"
                f"SELECT (rec).* FROM ("
                f"SELECT (u.r)::{table} AS rec FROM unnest(%s::text[]) AS u(r)"
                f") s",
                (literals,),
            )
        for seq, last_value, is_called in state["sequences"]:
            conn.execute(
                "SELECT setval(%s::regclass, %s, %s)",
                (seq, last_value, is_called),
            )
        conn.commit()
    finally:
        conn.close()


def discard(flavor: str) -> None:
    """Drop the reusable database for *flavor*; the next checkout rebuilds."""
    state = _STATES.pop(flavor, None)
    if state is not None:
        _drop_quietly(state["name"])


@contextlib.contextmanager
def checkout(
    flavor: str, build: Callable[[], str]
) -> Iterator[Optional[str]]:
    """Yield the reusable database name for *flavor*, or ``None`` to fall back.

    ``build`` returns the name of a freshly built database for the flavor
    (schema and seed data fully applied, no connections left open). It runs
    at most once per process per flavor unless a checkout drifts the schema
    or a reset fails, in which case the database is discarded and ``build``
    runs again on the next checkout.

    A ``None`` yield means the flavor is already checked out (nested use in
    the same process); the caller must fall back to its legacy
    clone-per-test path for that inner context.
    """
    state = _STATES.get(flavor)
    if state is not None and state["in_use"]:
        yield None
        return
    if state is None:
        name = build()
        state = _capture_baseline(name)
        _STATES[flavor] = state
        atexit.register(_drop_quietly, name)
    state["in_use"] = True
    try:
        yield state["name"]
    finally:
        state["in_use"] = False
        try:
            _reset(state)
        except SchemaDriftDetected:
            discard(flavor)
        except Exception:
            # A reset that fails for any other reason would silently leak
            # state into the next test; discard so the next checkout gets a
            # fresh build, then surface the defect.
            discard(flavor)
            raise


__all__ = [
    "SchemaDriftDetected",
    "checkout",
    "discard",
]
