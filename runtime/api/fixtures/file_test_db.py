"""Postgres-backed replacement for path-shaped test-DB helpers.

Many older per-module test helpers created a file-shaped ``db_path`` token,
initialized one connection, then re-opened that path directly in test bodies.
Under Postgres authority that pattern splits writes and reads across two
databases: initialization connects through the backend factory to the
DSN-pointed Postgres database while direct path opens read an empty local file.

This module gives those helpers one backend-aware seam to delegate to so the
same test bodies exercise the active authority. No caller infers the engine
from cwd or the presence of ``data/yoke.db``.

- :func:`init_test_db` — context manager yielding a legacy path-shaped
  ``db_path`` token with the schema applied to a disposable per-test Postgres
  database. The ``apply_schema`` strategy chooses which schema:
  ``schema.cmd_init`` (default, full production schema) or
  :func:`apply_fixture_schema_ddl` (the composed fixture schema).
  ``YOKE_PG_DSN`` is
  repointed for the context's lifetime, then restored and the database is
  dropped on exit. The yielded token threads through code-under-test unchanged;
  the backend factory ignores it and targets the DSN.
- :func:`apply_fixture_schema_ddl` — ``apply_schema`` strategy applying the
  composed fixture schema.
- :func:`connect_test_db` — connect to the native psycopg authority family
  against the repointed DSN. Drop-in for direct path opens the file-based
  helpers and their test bodies used to make.

Conversion is two edits per helper: the path-shaped init delegates to
:func:`init_test_db`, and each direct path open becomes
:func:`connect_test_db`.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Iterator


PRODUCTION_SCHEMA_FLAVOR = "production_schema"


@contextlib.contextmanager
def _repointed_dsn(name: str):
    """Point ``YOKE_PG_DSN`` at test database *name*, restoring on exit."""
    from yoke_core.domain import db_backend
    from runtime.api.fixtures import pg_testdb

    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = pg_testdb.dsn_for_test_database(name)
    try:
        yield
    finally:
        if prior is not None:
            os.environ[db_backend.PG_DSN_ENV] = prior
        else:
            os.environ.pop(db_backend.PG_DSN_ENV, None)


def _apply_production_schema() -> None:
    """Default schema strategy: ``schema.cmd_init`` + test-project identities."""
    from yoke_core.domain import schema
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_seed_test_helpers import (
        seed_project_identities,
    )

    schema.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


def _build_production_schema_db() -> str:
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    with _repointed_dsn(name):
        _apply_production_schema()
    return name


def _reusable_checkout(apply_schema):
    """Reusable-database checkout for the known schema strategies, or None.

    The default (production schema) and :func:`apply_fixture_schema_ddl`
    strategies produce one deterministic schema each, so their databases
    can be built once per worker and reset between uses. A caller-supplied
    strategy is an arbitrary callable whose output cannot be keyed, so it
    keeps the create/drop-per-use path.
    """
    from runtime.api.fixtures import pg_reusable_db, pg_testdb

    if apply_schema is None:
        return pg_reusable_db.checkout(
            PRODUCTION_SCHEMA_FLAVOR, _build_production_schema_db
        )
    if apply_schema is apply_fixture_schema_ddl:
        return pg_testdb.reusable_fixture_database()
    return None


@contextlib.contextmanager
def init_test_db(tmp_path: Path, apply_schema=None):
    """Yield a path-shaped ``db_path`` token with the schema applied.

    See the module docstring. The yielded value is always a string path-shaped
    compatibility token; the connection target is the repointed Postgres DSN.

    ``apply_schema`` is a zero-argument callable that applies the schema to the
    repointed ``YOKE_PG_DSN`` database. It defaults to ``schema.cmd_init``
    (the full production schema) plus the two baseline test-project
    identity rows (production init seeds no project rows; the shared
    test universe keeps them as fixture data). Pass
    :func:`apply_fixture_schema_ddl` for composed fixture-schema
    consumers, or a project-specific ``cmd_init`` wrapper for families
    that need a different schema.

    The two known strategies are served from a per-worker reusable
    database that ``pg_reusable_db`` resets between uses, so they run
    their schema build once per worker instead of once per test. Custom
    strategies (and nested contexts) fall back to a disposable per-use
    database that is dropped on exit.
    """
    from runtime.api.fixtures import pg_testdb

    db_path = str(tmp_path / "yoke.db")
    reusable_cm = _reusable_checkout(apply_schema)
    if reusable_cm is not None:
        with reusable_cm as reusable:
            if reusable is not None:
                with _repointed_dsn(reusable):
                    yield db_path
                return
            # Flavor already checked out (nested use): disposable fallback.
            name = pg_testdb.create_test_database()
            try:
                with _repointed_dsn(name):
                    (apply_schema or _apply_production_schema)()
                    yield db_path
            finally:
                pg_testdb.drop_test_database(name)
            return

    name = pg_testdb.create_test_database()
    try:
        with _repointed_dsn(name):
            apply_schema()
            yield db_path
    finally:
        pg_testdb.drop_test_database(name)


def apply_fixture_schema_ddl() -> None:
    """``apply_schema`` strategy applying the composed fixture schema."""
    from yoke_core.domain import db_backend
    from runtime.api.fixtures.schema_ddl import apply_fixture_schema

    conn = db_backend.connect()
    try:
        apply_fixture_schema(conn)
    finally:
        conn.close()


def iter_sql_script_statements(sql: str) -> Iterator[str]:
    """Yield complete SQL statements from an inline fixture script."""
    from yoke_core.domain.schema_init_apply import iter_schema_statements

    yield from iter_schema_statements(sql)


def apply_sql_script(conn, sql: str) -> None:
    """Apply an inline fixture script using native one-statement execution."""
    for statement in iter_sql_script_statements(sql):
        conn.execute(statement)


def apply_inline_ddl(ddl: str) -> None:
    """``apply_schema`` helper for fixture-local DDL scripts.

    The disposable Postgres DSN is already repointed by :func:`init_test_db`;
    use a raw psycopg connection so setup executes multi-statement DDL one
    native statement at a time.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect_psycopg()
    try:
        apply_sql_script(conn, ddl)
        conn.commit()
    finally:
        conn.close()


def connect_test_db(path: str):
    """Backend-aware connection to a :func:`init_test_db` database.

    Returns the native psycopg Postgres connection family over the repointed
    DSN; ``path`` is a compatibility token and is ignored by the connection
    factory.
    """
    from yoke_core.domain import db_backend

    return db_backend.connect(path)


__all__ = [
    "apply_fixture_schema_ddl",
    "apply_inline_ddl",
    "apply_sql_script",
    "connect_test_db",
    "init_test_db",
    "iter_sql_script_statements",
]
