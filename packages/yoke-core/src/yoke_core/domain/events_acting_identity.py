"""Required acting identity for attribution-sensitive events.

The function dispatcher binds its server-resolved actor around handler
execution.  Event emitters consult that request-local binding first, then the
canonical ambient session chain for direct local operations.  A genuinely
sessionless operation leaves ``session_id`` and ``actor_id`` empty.

Caller-supplied event-envelope identity is deliberately ignored for the event
names in :data:`ACTING_IDENTITY_EVENT_NAMES`: it must never disagree with the
identity that performed the write.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.events_session_actor import session_actor_lookup
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id


ACTING_IDENTITY_EVENT_NAMES = frozenset(
    {
        "ItemStatusChanged",
        "QARunCaptured",
        "QARunCompleted",
    }
)


class ActingEventIdentityUnavailable(RuntimeError):
    """An attribution-sensitive event could not resolve its acting actor."""


@dataclass(frozen=True)
class ActingEventIdentity:
    session_id: str
    actor_id: Optional[int]


@dataclass(frozen=True)
class _BoundIdentity:
    session_id: str
    actor_id: Optional[int]


_BOUND_IDENTITY: ContextVar[Optional[_BoundIdentity]] = ContextVar(
    "event_acting_identity",
    default=None,
)


def _numeric_actor_id(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() else None


@contextmanager
def acting_event_identity(
    *,
    session_id: Any,
    actor_id: Any,
) -> Iterator[None]:
    """Bind one dispatcher's resolved actor for nested event emission."""
    token = _BOUND_IDENTITY.set(
        _BoundIdentity(
            session_id=str(session_id or "").strip(),
            actor_id=_numeric_actor_id(actor_id),
        )
    )
    try:
        yield
    finally:
        _BOUND_IDENTITY.reset(token)


def _with_connection(conn: Any, db_path: Optional[str], operation):
    if conn is not None:
        return operation(conn)
    own_conn = db_backend.connect(db_path)
    try:
        return operation(own_conn)
    finally:
        own_conn.close()


def _session_actor_id(
    session_id: str,
    *,
    conn: Any,
    db_path: Optional[str],
    event_name: str,
) -> int:
    def lookup(active_conn):
        _found, actor_id = session_actor_lookup(active_conn, session_id)
        return actor_id

    actor_id = _with_connection(conn, db_path, lookup)
    if actor_id is None:
        raise ActingEventIdentityUnavailable(
            f"{event_name} acting identity has session_id {session_id!r} but "
            "no actor_id; repair harness_sessions.actor_id for that session "
            "before retrying the write."
        )
    return int(actor_id)


def resolve_acting_event_identity(
    event_name: str,
    *,
    conn: Any = None,
    db_path: Optional[str] = None,
) -> Optional[ActingEventIdentity]:
    """Resolve required attribution, or ``None`` for ordinary event names."""
    if event_name not in ACTING_IDENTITY_EVENT_NAMES:
        return None

    bound = _BOUND_IDENTITY.get()
    session_id = bound.session_id if bound is not None else ""
    actor_id = bound.actor_id if bound is not None else None
    if not session_id:
        session_id = str(resolve_ambient_session_id() or "").strip()
    if actor_id is None and session_id:
        actor_id = _session_actor_id(
            session_id,
            conn=conn,
            db_path=db_path,
            event_name=event_name,
        )
    return ActingEventIdentity(session_id=session_id, actor_id=actor_id)


def apply_acting_event_identity(
    envelope: dict[str, Any],
    *,
    conn: Any = None,
    db_path: Optional[str] = None,
) -> None:
    """Overwrite contracted event attribution with resolved acting identity."""
    identity = resolve_acting_event_identity(
        str(envelope.get("event_name") or ""),
        conn=conn,
        db_path=db_path,
    )
    if identity is None:
        return
    envelope["session_id"] = identity.session_id
    envelope["actor_id"] = identity.actor_id


__all__ = [
    "ACTING_IDENTITY_EVENT_NAMES",
    "ActingEventIdentityUnavailable",
    "acting_event_identity",
    "apply_acting_event_identity",
    "resolve_acting_event_identity",
]
