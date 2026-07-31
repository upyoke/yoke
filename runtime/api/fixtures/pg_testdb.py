"""Disposable PostgreSQL test-database management.

Operates against an externally provided cluster (CI's GitHub Actions
``postgres`` service, or the local ``pg_testcluster`` tool). The base cluster
connection comes from ``YOKE_PG_DSN``.

Two surfaces:

- :func:`setup_ambient_test_db` — called once per (xdist) worker from conftest.
  Creates a per-worker ambient test database with the fixture schema loaded and
  repoints ``YOKE_PG_DSN`` at it so ambient ``db_helpers.connect()`` calls
  during the suite land in an isolated, schema-loaded test database.
- :func:`test_database` / :func:`connect_test_database` — used by the ``test_db``
  fixture for per-test fresh databases with full isolation.

Schema-loaded databases are cloned from a per-worker template database
(``CREATE DATABASE ... TEMPLATE``) so the fixture DDL executes once per
worker rather than once per database.

Isolation between concurrent invocations lives here, at the layer that
provisions databases, so every entry path inherits it: the watcher wrapper,
raw ``pytest`` on one file, a ``-k`` filter, an IDE run, a QA registered
command. Names are minted through
:mod:`yoke_core.domain.pg_test_db_namespace`, which stamps each one with the
invocation's run tag.

Ownership guard: every create/drop/connect target name is asserted to carry
this invocation's run tag, so this module can never touch a non-test
database — nor another invocation's test database. Reclaiming what an
interrupted run left behind is the orphan sweep's job
(:mod:`yoke_core.tools.pg_testcluster`), never a running suite's.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import uuid
import weakref

import psycopg

from yoke_core.domain import db_backend, pg_test_db_namespace

TEST_DB_PREFIX = db_backend.POSTGRES_TEST_DB_PREFIX
AMBIENT_DB_PURPOSE = "ambient"

_BASE_DSN: "str | None" = None

# Session-level advisory locks are scoped to a database. All cooperating role
# tests acquire this key through the shared ``postgres`` maintenance database.
_CLUSTER_ROLE_AUTHORITY_LOCK_ID = 0x596F6B65526F6C65


def _apply_schema(conn) -> None:
    from runtime.api.fixtures.schema_ddl import apply_fixture_schema

    apply_fixture_schema(conn)


def _base_dsn() -> str:
    """Capture and return the original cluster DSN before any repointing."""
    global _BASE_DSN
    if _BASE_DSN is None:
        _BASE_DSN = db_backend.resolve_pg_dsn()
    return _BASE_DSN


def _with_dbname(dsn: str, dbname: str) -> str:
    # libpq key/value DSN: a later dbname= key wins, so appending overrides.
    return f"{dsn} dbname={dbname}"


def dsn_for_test_database(name: str) -> str:
    """Return a DSN for *name* on the captured test cluster.

    Test helpers must not derive disposable DB targets from the mutable current
    ``YOKE_PG_DSN``. Some tests intentionally monkeypatch that env var to
    fake live/cloud authorities; the base cluster captured at worker startup is
    the stable source for throwaway databases.
    """
    _assert_test_db(name)
    return _with_dbname(_base_dsn(), name)


def _assert_test_db(name: str) -> None:
    """Refuse any database this invocation did not create.

    The prefix check keeps the module away from real databases; the run-tag
    check keeps it away from the databases of every OTHER invocation sharing
    the cluster. Both are cheap, and the second is what makes concurrent runs
    safe without coordinating.
    """
    if not name.startswith(TEST_DB_PREFIX):
        raise RuntimeError(
            f"pg_testdb refuses to operate on non-test database {name!r}; "
            f"expected a {TEST_DB_PREFIX!r}-prefixed name"
        )
    if not pg_test_db_namespace.belongs_to_current_run(name):
        raise RuntimeError(
            f"pg_testdb refuses to operate on test database {name!r}, which "
            f"belongs to another invocation; this run owns "
            f"{pg_test_db_namespace.current_run_tag()!r}. Reclaiming another "
            f"run's databases is the orphan sweep's job "
            f"(python3 -m yoke_core.tools.pg_testcluster prune)"
        )


def _admin_execute(sql: str) -> None:
    # CREATE/DROP DATABASE cannot run inside a transaction; use autocommit on
    # the maintenance database.
    with psycopg.connect(_with_dbname(_base_dsn(), "postgres"), autocommit=True) as admin:
        admin.execute(sql)


@contextlib.contextmanager
def cluster_role_authority():
    """Isolate tests that mutate or attest cluster-global PostgreSQL roles.

    Disposable databases isolate schema and data, but roles are shared by the
    whole cluster. A narrow maintenance-database advisory lock lets xdist keep
    all unrelated tests parallel while preventing a temporary role in one
    worker from invalidating another worker's privileged-role inventory.
    """
    maintenance = _with_dbname(_base_dsn(), "postgres")
    with psycopg.connect(maintenance, autocommit=True) as authority:
        authority.execute(
            "SELECT pg_advisory_lock(%s)",
            (_CLUSTER_ROLE_AUTHORITY_LOCK_ID,),
        )
        try:
            yield
        finally:
            unlocked = authority.execute(
                "SELECT pg_advisory_unlock(%s)",
                (_CLUSTER_ROLE_AUTHORITY_LOCK_ID,),
            ).fetchone()
            if unlocked != (True,):
                raise RuntimeError(
                    "PostgreSQL cluster-role test authority was not held"
                )


def create_test_database(template: "str | None" = None) -> str:
    name = pg_test_db_namespace.database_name(uuid.uuid4().hex[:16])
    clone_source = f' TEMPLATE "{template}"' if template else ""
    _admin_execute(f'CREATE DATABASE "{name}"{clone_source}')
    return name


_FIXTURE_TEMPLATE_DB: "str | None" = None


def _fixture_template_db() -> str:
    """Return this process's fixture-schema template database, building it once.

    ``CREATE DATABASE ... TEMPLATE`` clones the schema-loaded template at the
    storage layer, so per-test databases skip re-executing the fixture DDL.
    The template is never connected to after its build completes (Postgres
    refuses to clone a database with live connections) and is dropped at
    process exit.
    """
    global _FIXTURE_TEMPLATE_DB
    if _FIXTURE_TEMPLATE_DB is None:
        name = create_test_database()
        conn = db_backend._open_native_postgres(dsn_for_test_database(name))
        try:
            _apply_schema(conn)
        finally:
            conn.close()
        atexit.register(lambda: drop_test_database(name))
        _FIXTURE_TEMPLATE_DB = name
    return _FIXTURE_TEMPLATE_DB


def drop_test_database(name: str) -> None:
    _assert_test_db(name)
    _admin_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def connect_test_database(name: str):
    _assert_test_db(name)
    return db_backend._open_native_postgres(dsn_for_test_database(name))


def drop_database_on_close(conn, name: str):
    """Attach disposable-DB cleanup to a native test connection.

    Plain helper functions that return a connection cannot use
    :func:`test_database` as a context manager without changing every caller.
    This keeps the old ``conn = make_db(); ...; conn.close()`` shape while
    guaranteeing the backing Postgres test database is closed and dropped.
    If a test forgets to close the connection, ``weakref.finalize`` runs the
    same cleanup when the native connection is garbage-collected.
    """
    _assert_test_db(name)
    native_close = conn.close

    def cleanup() -> None:
        try:
            native_close()
        except Exception:
            pass
        drop_test_database(name)

    finalizer = weakref.finalize(conn, cleanup)

    def close() -> None:
        if finalizer.alive:
            finalizer()

    conn.close = close
    conn._yoke_test_db_cleanup = finalizer
    conn._yoke_test_db_name = name
    return conn


@contextlib.contextmanager
def test_database():
    """Yield a connection to a fresh disposable test DB with the schema applied.

    Repoints ``YOKE_PG_DSN`` at the per-test database for the duration, so
    code-under-test that self-resolves its own connection (``db_helpers.connect``
    with no explicit conn) lands in the SAME database as the yielded fixture
    connection — not the shared ambient DB. Restores the prior DSN and drops the
    database on exit.

    The per-test database is cloned from this process's schema-loaded
    template database, so the fixture DDL executes once per worker instead
    of once per test.
    """
    name = create_test_database(template=_fixture_template_db())
    conn = connect_test_database(name)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = dsn_for_test_database(name)
    try:
        yield conn
    finally:
        if prior is not None:
            os.environ[db_backend.PG_DSN_ENV] = prior
        else:
            os.environ.pop(db_backend.PG_DSN_ENV, None)
        conn.close()
        drop_test_database(name)


# pytest collects any module-level callable named ``test_*`` as a test. This is a
# fixture-helper context manager imported into many test modules, not a test;
# flag it so pytest skips it regardless of import site (no per-importer alias).
test_database.__test__ = False


def setup_ambient_test_db() -> str:
    """Create + schema-load a per-worker ambient test DB and repoint the DSN.

    The name carries this invocation's run tag plus the worker id, so no two
    workers and no two concurrent invocations can collide. Normal worker
    shutdown drops the database; databases left by an interrupted run are
    reclaimed later by pg_testcluster's orphan sweep, never by a running suite.
    """
    base = _base_dsn()  # capture before repointing
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    template = _fixture_template_db()
    name = pg_test_db_namespace.database_name(
        f"{AMBIENT_DB_PURPOSE}_{worker}_{uuid.uuid4().hex[:12]}"
    )
    _admin_execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    atexit.register(lambda: drop_test_database(name))
    os.environ[db_backend.PG_DSN_ENV] = _with_dbname(base, name)
    return name


__all__ = [
    "AMBIENT_DB_PURPOSE",
    "TEST_DB_PREFIX",
    "cluster_role_authority",
    "create_test_database",
    "drop_test_database",
    "drop_database_on_close",
    "connect_test_database",
    "dsn_for_test_database",
    "test_database",
    "setup_ambient_test_db",
]
