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
  fixture for per-test isolated databases.

Schema-loaded databases are cloned from a per-worker template database
(``CREATE DATABASE ... TEMPLATE``) so the fixture DDL executes once per
worker rather than once per database. The per-test surface serves the
common case from one reusable clone per worker that ``pg_reusable_db``
resets between uses, so steady-state test traffic issues no
``CREATE DATABASE`` / ``DROP DATABASE`` at all.

Blank databases — the ones per-module helpers create and then load with
their own inline DDL — come from ``pg_blank_db_pool`` for the same
reason. Callers see no difference: a pooled database is handed out only
after it has been emptied and proven indistinguishable from a new one,
and one that cannot be proven so is really dropped.

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

# Re-exported: role isolation is a separate concern from provisioning, but
# callers have always reached it through this module.
from runtime.api.fixtures.pg_cluster_role_authority import (  # noqa: E402
    cluster_role_authority,
)


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
            f"(yoke dev run -- python3 -m yoke_core.tools.pg_testcluster prune)"
        )


def maintenance_dsn() -> str:
    """DSN for the cluster's maintenance database.

    Statements that cannot run inside the database they target — creating
    it, dropping it, terminating its backends — connect here instead.
    """
    return _with_dbname(_base_dsn(), "postgres")


def _admin_execute(sql: str) -> None:
    # CREATE/DROP DATABASE cannot run inside a transaction; use autocommit on
    # the maintenance database.
    with psycopg.connect(maintenance_dsn(), autocommit=True) as admin:
        admin.execute(sql)


def create_test_database(template: "str | None" = None, *, pooled: bool = True) -> str:
    """Return a fresh test database, blank or cloned from *template*.

    A blank database is served from this worker's pool when one is free
    (see :mod:`pg_blank_db_pool`) — the caller cannot tell the difference,
    because a pooled database is only reused after it has been emptied and
    proven indistinguishable from a new one. Pass ``pooled=False`` to
    require a genuinely new database; the pool itself does this to grow,
    and the fixture template build does it because a template is long
    lived rather than borrowed.
    """
    if template is None and pooled:
        from runtime.api.fixtures import pg_blank_db_pool

        if not pg_blank_db_pool.pooling_disabled():
            return pg_blank_db_pool.checkout()
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
        # Not pooled: the template outlives every borrower and is cloned
        # from, so it must be a database of its own for the whole process.
        name = create_test_database(pooled=False)

        def cleanup() -> None:
            drop_test_database(name, pooled=False)

        atexit.register(cleanup)
        try:
            conn = db_backend._open_native_postgres(dsn_for_test_database(name))
            try:
                _apply_schema(conn)
            finally:
                conn.close()
        except BaseException:
            try:
                drop_test_database(name, pooled=False)
            finally:
                atexit.unregister(cleanup)
            raise
        _FIXTURE_TEMPLATE_DB = name
    return _FIXTURE_TEMPLATE_DB


def drop_test_database(name: str, *, pooled: bool = True) -> None:
    """Dispose of *name*, returning it to the pool when it belongs there.

    A pooled database is emptied and kept for the next caller; anything
    else — including a pooled database that could not be proven empty —
    is really dropped. ``pooled=False`` skips the pool entirely so the
    pool can drop its own databases without recursing.
    """
    _assert_test_db(name)
    if pooled:
        from runtime.api.fixtures import pg_blank_db_pool

        if pg_blank_db_pool.release(name):
            return
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


REUSABLE_FIXTURE_FLAVOR = "fixture_schema"


def _build_reusable_fixture_db() -> str:
    return create_test_database(template=_fixture_template_db())


def reusable_fixture_database():
    """Checkout context for this worker's reusable fixture-schema database.

    Yields the database name, or ``None`` when the flavor is already checked
    out (nested use) and the caller must fall back to a per-use clone.
    Shared by every consumer of the fixture schema so one worker keeps one
    reusable database regardless of which fixture surface a test enters by.
    """
    from runtime.api.fixtures import pg_reusable_db

    return pg_reusable_db.checkout(REUSABLE_FIXTURE_FLAVOR, _build_reusable_fixture_db)


@contextlib.contextmanager
def test_database():
    """Yield a connection to an isolated, schema-loaded disposable test DB.

    Repoints ``YOKE_PG_DSN`` at the per-test database for the duration, so
    code-under-test that self-resolves its own connection (``db_helpers.connect``
    with no explicit conn) lands in the SAME database as the yielded fixture
    connection — not the shared ambient DB. Restores the prior DSN on exit.

    Isolation is served by this worker's reusable fixture-schema database:
    a single template clone per worker, reset to its baseline after every
    use (see ``pg_reusable_db``), instead of a ``CREATE DATABASE`` /
    ``DROP DATABASE`` pair per test — per-test clones saturate disk IO when
    several suites share the cluster. Nested contexts fall back to a
    per-use clone that is dropped on exit, so two live ``test_database()``
    contexts never share a database.
    """
    with reusable_fixture_database() as reusable:
        name = reusable if reusable is not None else _build_reusable_fixture_db()
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
            if reusable is None:
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
    "maintenance_dsn",
    "reusable_fixture_database",
    "test_database",
    "setup_ambient_test_db",
]
