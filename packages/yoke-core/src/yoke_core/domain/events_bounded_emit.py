"""Emit a disposable event without risking the caller's own transaction.

Some events sit in the same transaction as a durable write purely so the
audit correlation is exact. The durable row is the authority; the event is
telemetry that a severity filter, an events outage, or retention can take
away. Emitting it inline is still dangerous on Postgres, because a failed
statement aborts the whole transaction and would take the authoritative
write down with it — so the emission runs inside a savepoint that bounds
any database-level failure to the event alone.

A dropped event is logged rather than swallowed: the message names the
event, the reason the emitter gave, and where the durable fact actually
lives, so an operator reading the log is not left guessing whether the
work landed. A retired event name still raises, because that is the
caller naming an event that no longer exists rather than telemetry
failing.
"""

from __future__ import annotations

import logging
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.events_retired_name_guard import RetiredEventNameError

logger = logging.getLogger(__name__)

_SAVEPOINT = "yoke_disposable_event"


def emit_bounded(
    conn: Any,
    event_name: str,
    *,
    durable_fact: str,
    **emit_kwargs: Any,
) -> None:
    """Record ``event_name`` in ``conn``'s transaction, best effort.

    ``durable_fact`` names where the authoritative record of the same fact
    lives (a table, or the command that reads it) and is quoted in the
    warning when the event cannot be written. Callers pass the remaining
    :func:`yoke_core.domain.events.emit_event` keyword arguments through
    unchanged; ``conn`` and ``transactional`` are supplied here.
    """
    from yoke_core.domain.events import emit_event

    try:
        conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    except db_backend.database_error_types(conn) as exc:
        _warn(event_name, f"savepoint refused: {exc}", durable_fact)
        return

    reason = ""
    try:
        event = emit_event(
            event_name, conn=conn, transactional=True, **emit_kwargs
        )
        if not event.ok or not event.event_id:
            reason = event.reason or "unknown error"
    except RetiredEventNameError:
        _release(conn)
        raise
    except Exception as exc:
        reason = str(exc)

    # A refused emission may already have aborted the transaction, so the
    # savepoint is rolled back before it is released whenever anything
    # went wrong — releasing an aborted savepoint would fail in turn.
    if reason:
        _rollback_to(conn)
    _release(conn)
    if reason:
        _warn(event_name, reason, durable_fact)


def _rollback_to(conn: Any) -> None:
    try:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
    except db_backend.database_error_types(conn):
        pass


def _release(conn: Any) -> None:
    try:
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
    except db_backend.database_error_types(conn):
        pass


def _warn(event_name: str, reason: str, durable_fact: str) -> None:
    logger.warning(
        "%s telemetry was not recorded (%s); %s",
        event_name,
        reason,
        durable_fact,
    )


__all__ = ["emit_bounded"]
