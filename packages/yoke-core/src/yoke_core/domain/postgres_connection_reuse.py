"""Reusing ambient control-plane Postgres connections within one process.

Opening a control-plane connection is the expensive part of a call: through
an operator's SSH forward, TLS plus password authentication costs
about three seconds, against milliseconds for the statements that follow. A
process that makes many registered calls or event writes -- the API server,
a deployment driver on the local-postgres transport -- therefore keeps a
few authenticated sockets and hands them out again.

Each lease is still one unit of work, and a real ``psycopg.Connection``: a
:class:`ReusableConnection` built fresh around a retained libpq socket, so
its adapters, prepared-statement cache and attributes start clean. Its
``close()`` (and leaving a ``with`` block) returns the socket here instead of
closing it and leaves the handle closed, so a stale reference cannot touch
the next holder's session. Returning rolls back any open transaction --
exactly what closing did -- and runs ``DISCARD ALL``, so no setting, advisory
lock, cursor, listen, temp table or prepared statement one lease left is
visible to the next. A socket that fails its reset, or its liveness check on
the next checkout, is closed and a fresh one opened through the caller's
normal connect path, so readiness self-heal and managed secret rotation
recovery still see every real connect failure.

Only idle sockets are retained, at most :data:`MAX_IDLE_CONNECTIONS` per
process and none older than :data:`MAX_IDLE_SECONDS`; in-use connections are
bounded by the caller's own concurrency, as before. Only the unbound ambient
authority is reused: an explicit DSN or a ``db_backend.bound_pg_dsn`` scope
names temporary, often connection-limited authority, and its connections
close on ``close()``.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

import psycopg
from psycopg import pq

MAX_IDLE_CONNECTIONS = 4
MAX_IDLE_SECONDS = 60.0

TEST_TRACK_CONNECTIONS_ENV = "YOKE_TEST_TRACK_PG_CONNECTIONS"

SESSION_RESET_SQL = "DISCARD ALL"

_LOCK = threading.Lock()
_IDLE: list[tuple[str, Any, float]] = []
_TRACKED_TEST_CONNECTIONS: list[Any] = []
# A forked child shares its parent's sockets; closing them would terminate the
# parent's sessions, so the child keeps these references and never uses them.
_INHERITED_FROM_PARENT: list[Any] = []


def _forget_parent_connections() -> None:
    _INHERITED_FROM_PARENT.extend(entry[1] for entry in _IDLE)
    _IDLE.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forget_parent_connections)


class _ReturnedSocket:
    """Stands in for the libpq socket of a handle that returned it for reuse."""

    status = pq.ConnStatus.BAD
    transaction_status = pq.TransactionStatus.UNKNOWN

    def __getattr__(self, name):
        raise psycopg.OperationalError(
            "the connection is closed: it was returned for reuse; "
            "open a new one with db_backend.connect()"
        )


class ReusableConnection(psycopg.Connection):
    """A leased psycopg connection whose ``close()`` returns its socket for reuse."""

    _reuse_dsn: str = ""

    def close(self) -> None:
        if self.closed:
            return
        pgconn = self.pgconn
        reset = _reset_for_reuse(self)
        self.pgconn = _ReturnedSocket()
        self._closed = True
        if reset:
            _retain(self._reuse_dsn, pgconn)
        else:
            _finish_quietly(pgconn)


def _finish_quietly(pgconn) -> None:
    try:
        pgconn.finish()
    except Exception:  # noqa: BLE001 -- the socket is being discarded anyway
        pass


def _reset_for_reuse(conn: ReusableConnection) -> bool:
    if conn.broken or conn._num_transactions:
        return False
    try:
        if conn.info.transaction_status != pq.TransactionStatus.IDLE:
            conn.rollback()
        conn.autocommit = True
        conn.execute(SESSION_RESET_SQL)
    except psycopg.Error:
        return False
    return conn.info.transaction_status == pq.TransactionStatus.IDLE


def _retain(dsn: str, pgconn) -> None:
    with _LOCK:
        _IDLE.append((dsn, pgconn, time.monotonic()))
        evicted = [entry[1] for entry in _IDLE[:-MAX_IDLE_CONNECTIONS]]
        del _IDLE[:-MAX_IDLE_CONNECTIONS]
    for stale in evicted:
        _finish_quietly(stale)


def _checkout_idle(dsn: str, row_factory: Callable) -> ReusableConnection | None:
    while True:
        with _LOCK:
            index = next(
                (i for i in range(len(_IDLE) - 1, -1, -1) if _IDLE[i][0] == dsn),
                None,
            )
            if index is None:
                return None
            _, pgconn, returned_at = _IDLE.pop(index)
        if (
            time.monotonic() - returned_at <= MAX_IDLE_SECONDS
            and pgconn.status == pq.ConnStatus.OK
        ):
            conn = ReusableConnection(pgconn, row_factory=row_factory)
            try:
                conn.autocommit = True
                conn.execute("")
                return conn
            except psycopg.Error:
                pass
        _finish_quietly(pgconn)


def lease(
    dsn: str,
    *,
    autocommit: bool,
    row_factory: Callable,
    connect: Callable[..., Any],
) -> ReusableConnection:
    """Return a connection to *dsn* on an idle authenticated socket, or a new one.

    *connect* is ``connect_guarded_socket``; it is called with
    ``connection_class=ReusableConnection`` and its failures propagate
    unchanged. The caller applies the read-deadline wrapper to the result.
    """
    conn = _checkout_idle(dsn, row_factory)
    if conn is None:
        conn = connect(dsn, connection_class=ReusableConnection)
        conn.row_factory = row_factory
    conn._reuse_dsn = dsn
    conn.autocommit = autocommit
    return conn


def idle_connection_count() -> int:
    with _LOCK:
        return len(_IDLE)


def close_idle_connections() -> None:
    """Close every retained idle socket in this process."""
    with _LOCK:
        idle = [entry[1] for entry in _IDLE]
        _IDLE.clear()
    for pgconn in idle:
        _finish_quietly(pgconn)


def track_test_connection(conn):
    if os.environ.get(TEST_TRACK_CONNECTIONS_ENV) == "1":
        _TRACKED_TEST_CONNECTIONS.append(conn)
    return conn


def tracked_test_connection_count() -> int:
    """Return the current test connection tracker position."""
    return len(_TRACKED_TEST_CONNECTIONS)


def close_test_connections_since(index: int) -> None:
    """Close connections a pytest item leaked after *index*, then drain reuse.

    The active runtime does not enable tracking. Pytest turns it on so native
    psycopg connections left open by fixture shapes cannot accumulate across a
    broad xdist run and exhaust the shared test Postgres service, and so no
    idle socket outlives the test database it was opened against.
    """
    connections = list(reversed(_TRACKED_TEST_CONNECTIONS[index:]))
    del _TRACKED_TEST_CONNECTIONS[index:]
    for conn in connections:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 -- teardown keeps closing the rest
            pass
    close_idle_connections()


__all__ = [
    "MAX_IDLE_CONNECTIONS",
    "MAX_IDLE_SECONDS",
    "ReusableConnection",
    "SESSION_RESET_SQL",
    "TEST_TRACK_CONNECTIONS_ENV",
    "close_idle_connections",
    "close_test_connections_since",
    "idle_connection_count",
    "lease",
    "track_test_connection",
    "tracked_test_connection_count",
]
