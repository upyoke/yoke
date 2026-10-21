"""Postgres schema templates for helpers that pass path-shaped test tokens.

:func:`init_test_db` chooses a per-worker template by schema callable identity.
The default and explicit ``schema.cmd_init`` share the complete production schema
with test-project identities and sites; :func:`apply_test_schema` selects
that same template. Other callables retain their own schema and seed data.
Tests receive reusable clones reset after checkout. Nested contexts receive
independent template clones that are dropped on exit.

:func:`seeded_schema` builds a flavor from a clone of a base flavor's template,
so seeds over the production or booted schema never replay initialization.
:func:`booted_universe_database` clones the booted template for tests that
need a production-booted universe without test seeds.

``YOKE_PG_DSN`` points at the checkout only for its context's lifetime.
:func:`connect_test_db` opens that native authority; the yielded path token
passes through consumers but does not select a database. Per-test machine
configuration belongs in the consuming fixture after checkout, since schema
callables run only when the template is built.

Contributor guide: docs/testing-verification/test-database-templates.md.
"""

from __future__ import annotations

import atexit
import contextlib
import os
from pathlib import Path
from typing import Iterator


_SCHEMA_TEMPLATES: dict[int, tuple[object, str]] = {}


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
    """Production init chain + baseline test-project identities and sites."""
    from yoke_core.domain.db_helpers import connect
    from runtime.api.fixtures.production_schema import initialize_test_schema

    conn = connect()
    try:
        initialize_test_schema(conn)
    finally:
        conn.close()


def apply_booted_schema() -> None:
    """Initialize through the production chain only, without test seeds."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

    run_init_chain_at_dsn(os.environ[db_backend.PG_DSN_ENV], emit=lambda _line: None)


class _SeededSchema:
    """A flavor whose template clones *base*'s template, then applies *seed*."""

    def __init__(self, base, seed):
        self.base = base
        self.seed = seed
        self.__module__ = seed.__module__
        self.__qualname__ = seed.__qualname__

    def __call__(self) -> None:
        _schema_strategy(self.base)()
        self.seed()


def seeded_schema(base, seed):
    """Return a flavor built as a clone of *base*'s template plus *seed*.

    *base* is ``apply_test_schema``, ``apply_booted_schema`` or another
    flavor. Only *seed* runs when the template is built; calling the flavor
    directly applies *base* and then *seed*. Bind the result at module level:
    its identity is the flavor.
    """
    return _SeededSchema(base, seed)


def _schema_strategy(apply_schema):
    from yoke_core.domain import schema

    if (
        apply_schema is None
        or apply_schema is schema.cmd_init
        or apply_schema is apply_test_schema
    ):
        return _apply_production_schema
    return apply_schema


def _schema_template_db(strategy) -> str:
    """Build each callable's schema once per worker, retaining its seed data."""
    from runtime.api.fixtures import pg_testdb

    key = id(strategy)
    if key not in _SCHEMA_TEMPLATES:
        build = strategy
        base = None
        if isinstance(strategy, _SeededSchema):
            build = strategy.seed
            base = _schema_template_db(_schema_strategy(strategy.base))
        name = pg_testdb.create_test_database(template=base, pooled=False)
        try:
            with _repointed_dsn(name):
                build()
        except BaseException:
            pg_testdb.drop_test_database(name, pooled=False)
            raise
        # Retain the callable so its identity cannot be recycled by Python.
        _SCHEMA_TEMPLATES[key] = (strategy, name)
        atexit.register(pg_testdb.drop_test_database, name, pooled=False)
    return _SCHEMA_TEMPLATES[key][1]


def _clone_schema_database(strategy) -> str:
    from runtime.api.fixtures import pg_testdb

    return pg_testdb.create_test_database(template=_schema_template_db(strategy))


def _reusable_checkout(strategy):
    """All schema callables use the existing reusable baseline reset."""
    from runtime.api.fixtures import pg_reusable_db

    return pg_reusable_db.checkout(
        id(strategy), lambda: _clone_schema_database(strategy)
    )


@contextlib.contextmanager
def init_test_db(tmp_path: Path, apply_schema=None):
    """Yield a path token targeting an isolated schema-loaded test database.

    Every zero-argument schema callable has a per-worker Postgres template.
    Default and explicit ``schema.cmd_init`` share the production flavor,
    including baseline test-project identities. Other callables retain their
    own schema and seeds. A reusable clone is reset after use; nested contexts
    and schema-drift replacements clone the same template without replaying
    schema initialization. Templates are never handed to tests.

    Use a distinct callable when its schema or seed inputs differ: callable
    identity is the flavor, not its name or source text.
    """
    from runtime.api.fixtures import pg_testdb

    db_path = str(tmp_path / "yoke.db")
    strategy = _schema_strategy(apply_schema)
    with _reusable_checkout(strategy) as reusable:
        name = reusable if reusable is not None else _clone_schema_database(strategy)
        try:
            with _repointed_dsn(name):
                yield db_path
        finally:
            if reusable is None:
                pg_testdb.drop_test_database(name)


@contextlib.contextmanager
def booted_universe_database() -> Iterator[str]:
    """Yield a fresh clone of the booted-universe template, dropped on exit."""
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database(
        template=_schema_template_db(apply_booted_schema)
    )
    try:
        yield name
    finally:
        pg_testdb.drop_test_database(name)


def apply_empty_schema() -> None:
    """Select a stable empty database flavor for inline or boot tests."""


def apply_test_schema() -> None:
    """Initialize a disposable database through production boot and test seeds."""
    _apply_production_schema()


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
    "apply_booted_schema",
    "apply_test_schema",
    "apply_empty_schema",
    "apply_inline_ddl",
    "apply_sql_script",
    "booted_universe_database",
    "connect_test_db",
    "init_test_db",
    "iter_sql_script_statements",
    "seeded_schema",
]
