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
    that need a different schema; the per-test-DB lifecycle is identical
    regardless of strategy.
    """
    from yoke_core.domain import db_backend, schema

    db_path = str(tmp_path / "yoke.db")
    if apply_schema is None:
        def apply_schema() -> None:
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

    from runtime.api.fixtures import pg_testdb

    # Disposable per-test database on the shared cluster. The apply_schema
    # strategy builds the schema against the repointed DSN. YOKE_PG_DSN is
    # repointed at the per-test database for the context's lifetime, then
    # restored and the database dropped.
    name = pg_testdb.create_test_database()
    new_dsn = pg_testdb.dsn_for_test_database(name)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = new_dsn
    try:
        apply_schema()
        yield db_path
    finally:
        if prior is not None:
            os.environ[db_backend.PG_DSN_ENV] = prior
        else:
            os.environ.pop(db_backend.PG_DSN_ENV, None)
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
