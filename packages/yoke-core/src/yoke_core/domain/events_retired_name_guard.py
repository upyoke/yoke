"""Refuse emission of event names registered as ``status='retired'``.

The native emitter (``yoke_core.domain.events.emit_event``) and the
lower-level row insert (``yoke_core.domain.events_writes.cmd_insert``)
both call :func:`assert_event_name_not_retired` before writing. Without
the guard a future producer could re-introduce one of the un-prefixed
``ToolCall*`` / ``Session*`` names that the rename rollout retired.

Unregistered names pass through silently; registration drift is a
different invariant. A missing ``event_registry`` table also passes —
minimal-schema test DBs and transitional bootstrap states must not be
broken by this gate.
"""

from __future__ import annotations

from typing import Any, Optional


class RetiredEventNameError(ValueError):
    """Raised when ``event_registry.status='retired'`` for the given name."""

    def __init__(self, event_name: str, successor_name: Optional[str] = None) -> None:
        self.event_name = event_name
        self.successor_name = successor_name
        replacement_hint = (
            f"Use active replacement {successor_name!r}."
            if successor_name
            else "Use an active replacement from event_registry."
        )
        super().__init__(
            f"event_name={event_name!r} is registered with status='retired' "
            f"and cannot be emitted. {replacement_hint}"
        )


def assert_event_name_not_retired(
    conn_or_path: Any,
    event_name: str,
) -> None:
    """Raise :class:`RetiredEventNameError` when the registry retires the name.

    Accepts either a live DB connection or a DB path token. When given a path,
    opens a short-lived connection and closes it on return. Passing ``None`` is
    a no-op (caller resolved no DB target).
    """
    if conn_or_path is None:
        return
    from yoke_core.domain import db_backend

    own_conn = None
    try:
        if isinstance(conn_or_path, str):
            # A DB path: open a short-lived connection through the backend
            # factory (sqlite file on SQLite, the sqlite3-compatible facade
            # over the DSN on Postgres) so the guard never opens a raw sqlite
            # connection while the Postgres backend is selected.
            try:
                own_conn = db_backend.connect(conn_or_path)
            except db_backend.operational_error_types():
                # Bad path / file inaccessible. The native emitter's
                # non-fatal contract owns the user-facing degradation;
                # the guard fails open here so it can.
                return
            conn = own_conn
        else:
            # Already a live connection — a sqlite3.Connection or the Postgres
            # facade. Use it directly (the facade is not a sqlite3.Connection,
            # so a type check against sqlite3.Connection would misroute it).
            conn = conn_or_path
        savepoint = "_yoke_event_registry_guard"
        use_savepoint = own_conn is None and db_backend.connection_is_postgres(conn)
        savepoint_created = False
        try:
            if use_savepoint:
                conn.execute(f"SAVEPOINT {savepoint}")
                savepoint_created = True
            row = conn.execute(
                "SELECT status FROM event_registry WHERE event_name=%s",
                (event_name,),
            ).fetchone()
            successor_row = conn.execute(
                "SELECT event_name FROM event_registry "
                "WHERE event_name=%s AND status='active'",
                (f"Harness{event_name}",),
            ).fetchone()
            if use_savepoint:
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except db_backend.operational_error_types(conn=conn):
            # event_registry table absent (minimal-schema test DBs,
            # bootstrap). The guard fails open in that case. On Postgres a
            # missing-relation error aborts the current statement; keep the
            # cleanup local so caller-owned transactions do not lose earlier
            # writes made before best-effort event emission.
            if savepoint_created:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    pass
            return
        if row is None:
            return
        if row[0] == "retired":
            successor = successor_row[0] if successor_row is not None else None
            raise RetiredEventNameError(event_name, successor)
    finally:
        if own_conn is not None:
            own_conn.close()
