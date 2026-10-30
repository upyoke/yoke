"""Postgres authority connection factory.

Yoke's active control plane is Postgres. Backend selection is not runtime or
environment driven; callers must not infer authority from cwd, checkout shape,
or the presence of a ``data/yoke.db`` file.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import os
import sqlite3
from typing import Optional

from yoke_contracts import control_plane_locality
from yoke_contracts.control_plane_locality import PG_DSN_ENV, PG_DSN_FILE_ENV
from yoke_core.domain import postgres_connection_reuse, universe_source_pause
from yoke_core.domain.db_row import PostgresRow, postgres_row_factory
from yoke_core.domain.postgres_control_plane_connection import (
    bind_read_deadline,
    connect_guarded_socket,
    open_guarded_postgres,
)

POSTGRES = "postgres"
POSTGRES_TEST_DB_PREFIX = "yoke_test_"

_BOUND_PG_DSN: ContextVar[Optional[str]] = ContextVar(
    "yoke_bound_pg_dsn",
    default=None,
)


@contextmanager
def bound_pg_dsn(dsn: str) -> Iterator[None]:
    """Bind this execution context to one explicit Postgres authority.

    Unlike an environment-variable override, this is safe when concurrent
    request handlers need different staging authorities in the same process.
    Child calls through :func:`resolve_pg_dsn`, :func:`connect`, and the
    domain init modules inherit the binding; unrelated threads and tasks do
    not. Bound authority is temporary and often connection-limited: its
    connections close on ``close()``, never retained for reuse.
    """
    if not dsn.strip():
        raise ValueError("the bound Postgres DSN must not be empty")
    token = _BOUND_PG_DSN.set(dsn)
    try:
        yield
    finally:
        _BOUND_PG_DSN.reset(token)


def pg_dsn_is_bound() -> bool:
    """Return whether this execution context has an explicit DSN binding."""
    return _BOUND_PG_DSN.get() is not None


def is_postgres() -> bool:
    return True


def connection_is_postgres(conn) -> bool:
    """Return the dialect of an *existing* connection by type, not env.

    Existing SQLite fixtures remain SQLite; all other connections are Postgres.
    """
    for attr in ("_inner", "_conn"):
        inner = getattr(conn, attr, None)
        if isinstance(inner, sqlite3.Connection):
            return False
    return not isinstance(conn, sqlite3.Connection)


def resolve_pg_dsn(dbname: Optional[str] = None) -> str:
    """Return the Postgres DSN from the selected authority binding.

    When *dbname* is given it is appended as a trailing ``dbname=`` key; in a
    libpq key/value DSN the last occurrence wins, so this overrides any
    database named in the base DSN. Used by the test-DB helper to target a
    freshly created disposable database on the shared cluster.
    """
    dsn = _BOUND_PG_DSN.get() or os.environ.get(PG_DSN_ENV)
    if not dsn:
        dsn_file = os.environ.get(PG_DSN_FILE_ENV)
        if dsn_file:
            with open(dsn_file, encoding="utf-8") as handle:
                dsn = handle.read().strip()
    if not dsn:
        from yoke_core.domain.cloud_db_secret_dsn import resolve_dsn_from_env

        dsn = resolve_dsn_from_env()
    if not dsn:
        try:
            from yoke_core.domain import yoke_connected_env

            resolved = yoke_connected_env.resolve_postgres_dsn(
                dsn_env=PG_DSN_ENV,
                dsn_file_env=PG_DSN_FILE_ENV,
            )
            dsn = resolved.dsn
        except yoke_connected_env.ConnectedEnvNotLocalPostgres as exc:
            # The selected env is non-local (e.g. https): the message already
            # teaches the YOKE_ENV override recipe. Generic DSN setup framing
            # would bury it.
            raise RuntimeError(str(exc)) from exc
        except yoke_connected_env.ConnectedEnvError as exc:
            raise RuntimeError(
                f"{PG_DSN_ENV}, {PG_DSN_FILE_ENV}, managed database secret "
                f"environment, or a usable {yoke_connected_env.BINDING_RELATIVE_PATH} "
                f"credential source must be set for {POSTGRES} authority: {exc}"
            ) from exc
    if dbname:
        return f"{dsn} dbname={dbname}"
    return dsn


def _open_native_postgres(dsn: str, *, autocommit: bool = False):
    """Open a native psycopg connection to *dsn* that closes on ``close()``."""
    universe_source_pause.require_running(dsn)
    return postgres_connection_reuse.track_test_connection(
        open_guarded_postgres(
            dsn, autocommit=autocommit, row_factory=postgres_row_factory
        )
    )


def _lease_ambient_postgres(
    dsn: str, *, autocommit: bool = False, row_factory=postgres_row_factory
):
    """Lease a reused guarded authority connection; ``close()`` returns it."""
    universe_source_pause.require_running(dsn)
    conn = postgres_connection_reuse.lease(
        dsn,
        autocommit=autocommit,
        row_factory=row_factory,
        connect=connect_guarded_socket,
    )
    return postgres_connection_reuse.track_test_connection(bind_read_deadline(conn))


def _managed_secret_is_active_authority() -> bool:
    """Return whether ambient connection acquisition uses the managed secret."""
    if pg_dsn_is_bound():
        return False
    if os.environ.get(PG_DSN_ENV) or os.environ.get(PG_DSN_FILE_ENV):
        return False
    from yoke_core.domain.cloud_db_secret_dsn import env_binding_selected

    if env_binding_selected():
        return True
    try:
        from yoke_core.domain import yoke_connected_env

        return yoke_connected_env.managed_secret_selected()
    except Exception:
        return False


def _open_with_managed_rotation_recovery(opener, current_dsn: str):
    """Open with a narrow managed-secret rotation recovery sequence.

    Postgres ``InvalidPassword`` is the only signal that selects recovery.
    Refreshing ``AWSCURRENT`` first handles a process cache that spans a
    completed rotation. ``AWSPREVIOUS`` then covers the brief managed-rotation
    interval where the secret label and database password are not yet aligned.
    """
    import psycopg

    try:
        return opener(current_dsn)
    except psycopg.errors.InvalidPassword as current_error:
        if not _managed_secret_is_active_authority():
            raise

        from yoke_core.domain import cloud_db_secret_dsn

        cloud_db_secret_dsn.clear_cache()
        refreshed_dsn = resolve_pg_dsn()
        try:
            return opener(refreshed_dsn)
        except psycopg.errors.InvalidPassword:
            try:
                if cloud_db_secret_dsn.env_binding_selected():
                    previous_dsn = cloud_db_secret_dsn.resolve_previous_dsn_from_env()
                else:
                    from yoke_core.domain import yoke_connected_env

                    previous_dsn = yoke_connected_env.resolve_previous_postgres_dsn()
            except Exception:
                raise current_error
            return opener(previous_dsn)


def connect(path: Optional[str] = None, *, busy_timeout_ms: Optional[int] = None):
    """Return a connection to the Postgres authority.

    The *path* and *busy_timeout_ms* arguments are ignored compatibility slots.
    Rows are native psycopg values with name and positional access; callers use
    psycopg paramstyle (``%s``) and explicit ``RETURNING`` for generated ids.
    Ambient ``close()`` keeps the socket for reuse; :func:`bound_pg_dsn` closes.

    Routed through the connected-env readiness layer: when the operator's local
    Aurora SSH forward is down (e.g. after a WiFi change), the failed connect is
    self-healed (tunnel restarted) and retried once before raising a loud,
    redacted :class:`connected_env_readiness.ConnectedEnvUnavailable`. The
    readiness check is at connection acquisition (cache-gated), not per
    statement, and is a noop when an explicit ``YOKE_PG_DSN`` is pinned.

    Refused outright where the active control plane is reached over https:
    that machine has no local database to open, so the call has to relay
    instead. See :mod:`yoke_contracts.control_plane_locality`.
    """
    control_plane_locality.refuse_direct_connection("db_backend.connect()")
    if pg_dsn_is_bound():
        return _open_native_postgres(resolve_pg_dsn())
    from yoke_core.domain import connected_env_readiness as _readiness

    def _open_resolved():
        return _open_with_managed_rotation_recovery(
            lambda target: _lease_ambient_postgres(target),
            resolve_pg_dsn(),
        )

    return _readiness.connect_with_readiness(_open_resolved)


def connect_psycopg(dsn: Optional[str] = None, *, autocommit: bool = False):
    """Return a tuple-row psycopg connection with connected-env self-heal.

    For callers that need psycopg-native APIs (e.g. the board renderer's
    ``BoardDB``, which branches on ``psycopg.errors.*`` and returns positional
    tuples). Shares the same acquisition-time readiness + single-retry
    self-heal contract as :func:`connect`.

    The no-*dsn* form leases a reused ambient authority connection and carries
    the same remote-control-plane refusal as :func:`connect`. An explicit *dsn*
    or a :func:`bound_pg_dsn` scope is the caller's to open; ``close()`` closes it.
    """
    if dsn is None:
        control_plane_locality.refuse_direct_connection("db_backend.connect_psycopg()")

    from yoke_core.domain import connected_env_readiness as _readiness

    from psycopg.rows import tuple_row

    def _open():
        if dsn is not None or pg_dsn_is_bound():
            universe_source_pause.require_running(dsn or resolve_pg_dsn())
            return postgres_connection_reuse.track_test_connection(
                open_guarded_postgres(dsn or resolve_pg_dsn(), autocommit=autocommit)
            )
        return _open_with_managed_rotation_recovery(
            lambda target: _lease_ambient_postgres(
                target, autocommit=autocommit, row_factory=tuple_row
            ),
            resolve_pg_dsn(),
        )

    if dsn is not None or pg_dsn_is_bound():
        return _open()
    return _readiness.connect_with_readiness(_open)


def integrity_error_types(conn=None) -> tuple:
    """Exception type(s) a constraint/uniqueness violation raises on the active
    backend, as a tuple suitable for ``pytest.raises``.

    SQLite raises :class:`sqlite3.IntegrityError`; the Postgres authority surfaces
    psycopg's ``IntegrityError`` (e.g. ``UniqueViolation``). Code asserting a
    constraint violation uses this so the expected-exception target is correct
    on both engines instead of pinning the SQLite-only type.

    When *conn* is given, the dialect is read from the **actual connection** so
    minimal SQLite fixtures can still assert their native exception type while
    Yoke authority uses psycopg.
    """
    if conn is not None and not connection_is_postgres(conn):
        return (sqlite3.IntegrityError,)
    import psycopg

    return (psycopg.errors.IntegrityError,)


def database_error_types(conn=None) -> tuple:
    """Exception type(s) any database operation can raise on the actual
    connection dialect, as a tuple suitable for ``except``.

    Use this for broad best-effort guards that previously caught
    ``sqlite3.Error`` and should keep the same "database failure only" scope
    while running through Yoke's Postgres authority.
    """
    if conn is not None and not connection_is_postgres(conn):
        return (sqlite3.Error,)
    import psycopg

    return (psycopg.Error,)


def operational_error_types(conn=None) -> tuple:
    """Exception type(s) a malformed / missing-relation query raises, as a tuple
    suitable for ``except`` / ``pytest.raises``.

    SQLite raises :class:`sqlite3.OperationalError` (e.g. ``no such table``);
    the Postgres authority surfaces psycopg's ``Error`` family (e.g.
    ``UndefinedTable``). Best-effort code that swallows a "table not present
    yet" query uses this so the swallow branch fires on both engines instead of
    pinning the SQLite-only type and letting the psycopg error escape.

    When *conn* is given, the dialect is read from the **actual connection**
    (:func:`connection_is_postgres`) rather than the process default. A caller
    can hold a genuine SQLite connection (e.g. a fixture that seeds a raw
    SQLite file and hands it to factory-routed render code): keying off the
    default would return the psycopg type and let the real
    ``sqlite3.OperationalError`` escape the swallow branch. The no-arg form
    keeps the default behavior for call sites that do not hold a connection.
    """
    if conn is not None:
        use_postgres = connection_is_postgres(conn)
    else:
        use_postgres = True
    if use_postgres:
        import psycopg

        return (psycopg.Error,)
    return (sqlite3.OperationalError,)


__all__ = [
    "POSTGRES",
    "PostgresRow",
    "PG_DSN_ENV",
    "PG_DSN_FILE_ENV",
    "POSTGRES_TEST_DB_PREFIX",
    "bound_pg_dsn",
    "pg_dsn_is_bound",
    "is_postgres",
    "resolve_pg_dsn",
    "connect",
    "connect_psycopg",
    "integrity_error_types",
    "database_error_types",
    "operational_error_types",
]
