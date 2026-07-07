"""Postgres authority connection factory.

Yoke's active control plane is Postgres. Backend selection is not runtime or
environment driven; callers must not infer authority from cwd, checkout shape,
or the presence of a ``data/yoke.db`` file.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

POSTGRES = "postgres"
PG_DSN_ENV = "YOKE_PG_DSN"
PG_DSN_FILE_ENV = "YOKE_PG_DSN_FILE"
POSTGRES_TEST_DB_PREFIX = "yoke_test_"
TEST_TRACK_CONNECTIONS_ENV = "YOKE_TEST_TRACK_PG_CONNECTIONS"

_TRACKED_TEST_CONNECTIONS = []


def is_postgres() -> bool:
    return True


def connection_is_postgres(conn) -> bool:
    """Return the dialect of an *existing* connection by type, not env.

    A real :class:`sqlite3.Connection` is always SQLite; anything else is the
    Postgres connection family. Thin test wrappers around a real SQLite
    connection are also SQLite. Helpers that RECEIVE a connection (schema
    introspection, etc.) must branch on this because a caller can still hold a
    genuine SQLite connection (e.g. a migration-model SQLite validation
    file opened explicitly).
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
    dsn = os.environ.get(PG_DSN_ENV)
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


class PostgresRow:
    """Psycopg row object with name and positional access.

    This is a row-shape adapter, not a connection or SQL dialect facade. It lets
    callers migrate off the sqlite-shaped connection bridge without forcing a
    same-commit rewrite of every historical ``row[0]`` assertion/helper.
    """

    __slots__ = ("_columns", "_index", "_values")

    def __init__(self, columns: tuple[str, ...], values: tuple) -> None:
        self._columns = columns
        self._index = {name: i for i, name in enumerate(columns)}
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key) -> bool:
        return key in self._index

    def __eq__(self, other) -> bool:
        if isinstance(other, dict):
            return dict(self.items()) == other
        if isinstance(other, (list, tuple)):
            return self._values == tuple(other)
        return NotImplemented

    def __repr__(self) -> str:
        return repr(dict(self.items()))

    def get(self, key: str, default=None):
        idx = self._index.get(key)
        return default if idx is None else self._values[idx]

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def values(self) -> tuple:
        return self._values

    def items(self):
        return zip(self._columns, self._values)


def _postgres_row_factory(cursor):
    columns = tuple(desc.name for desc in (cursor.description or ()))

    def make_row(values):
        return PostgresRow(columns, values)

    return make_row


def _open_native_postgres(dsn: str, *, autocommit: bool = False):
    """Open a native psycopg authority connection with name-aware rows."""
    import psycopg

    return _track_test_connection(
        psycopg.connect(dsn, autocommit=autocommit, row_factory=_postgres_row_factory)
    )


def _track_test_connection(conn):
    if os.environ.get(TEST_TRACK_CONNECTIONS_ENV) == "1":
        _TRACKED_TEST_CONNECTIONS.append(conn)
    return conn


def tracked_test_connection_count() -> int:
    """Return the current test connection tracker position."""
    return len(_TRACKED_TEST_CONNECTIONS)


def close_tracked_test_connections_since(index: int) -> None:
    """Close tracked Postgres connections opened after *index*."""
    if index >= len(_TRACKED_TEST_CONNECTIONS):
        return
    connections = list(reversed(_TRACKED_TEST_CONNECTIONS[index:]))
    del _TRACKED_TEST_CONNECTIONS[index:]
    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass


def close_tracked_test_connections() -> None:
    """Close Postgres connections leaked by the current pytest item.

    The active runtime does not enable tracking. Pytest turns it on so native
    psycopg connections left open by legacy fixture shapes cannot accumulate
    across a broad xdist run and exhaust the shared test Postgres service.
    """
    close_tracked_test_connections_since(0)


def connect(path: Optional[str] = None, *, busy_timeout_ms: Optional[int] = None):
    """Return a connection to the Postgres authority.

    The *path* and *busy_timeout_ms* arguments are ignored compatibility slots.
    Rows are native psycopg values with name and positional access; callers use
    psycopg paramstyle (``%s``) and explicit ``RETURNING`` for generated ids.

    Routed through the connected-env readiness layer: when the operator's local
    Aurora SSH forward is down (e.g. after a WiFi change), the failed connect is
    self-healed (tunnel restarted) and retried once before raising a loud,
    redacted :class:`connected_env_readiness.ConnectedEnvUnavailable`. The
    readiness check is at connection acquisition (cache-gated), not per
    statement, and is a noop when an explicit ``YOKE_PG_DSN`` is pinned.
    """
    from yoke_core.domain import connected_env_readiness as _readiness

    return _readiness.connect_with_readiness(
        lambda: _open_native_postgres(resolve_pg_dsn())
    )


def connect_psycopg(dsn: Optional[str] = None, *, autocommit: bool = False):
    """Return a tuple-row psycopg connection with connected-env readiness +
    reactive self-heal.

    For callers that need psycopg-native APIs (e.g. the board renderer's
    ``BoardDB``, which branches on ``psycopg.errors.*`` and returns positional
    tuples). Shares the same acquisition-time readiness + single-retry
    self-heal contract as :func:`connect`.
    """
    import psycopg

    from yoke_core.domain import connected_env_readiness as _readiness

    def _open():
        target = dsn if dsn is not None else resolve_pg_dsn()
        return _track_test_connection(psycopg.connect(target, autocommit=autocommit))

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
    "PG_DSN_ENV",
    "PG_DSN_FILE_ENV",
    "POSTGRES_TEST_DB_PREFIX",
    "TEST_TRACK_CONNECTIONS_ENV",
    "is_postgres",
    "resolve_pg_dsn",
    "connect",
    "connect_psycopg",
    "close_tracked_test_connections",
    "close_tracked_test_connections_since",
    "tracked_test_connection_count",
    "integrity_error_types",
    "database_error_types",
    "operational_error_types",
]
