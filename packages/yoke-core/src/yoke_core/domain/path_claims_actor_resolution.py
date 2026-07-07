"""Session/auth-bound actor resolution for mutation callers.

The canonical explicit → session ladder: an explicit actor id wins
(after a presence check), else the caller's session — explicit
``session_id`` argument, then the ambient session — maps to
``harness_sessions.actor_id``. There is no machine-default rung; actor
identity is bound by session registration and the token-auth boundary.
Consumers: path-claim registration and ``backlog_create_op`` source
resolution.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actors import validate_actor_id
from yoke_core.domain.schema_common import _column_exists, _table_exists


class ActorResolutionUnavailable(Exception):
    """Raised when no valid actor can be resolved for a path-claim writer."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    return row[key] if hasattr(row, "keys") else row[0]


def _current_session_id() -> str:
    try:
        from yoke_core.api.service_client_shared_session_resolver import (
            current_session_id,
        )
    except ImportError:
        return ""
    return current_session_id()


def _session_actor_id(conn: Any, session_id: str) -> Optional[int]:
    if not session_id:
        return None
    if not _table_exists(conn, "harness_sessions"):
        return None
    if not _column_exists(conn, "harness_sessions", "actor_id"):
        return None
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    raw = _row_value(row, "actor_id")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        actor_id = int(raw)
    except ValueError as exc:
        raise ActorResolutionUnavailable(
            f"harness session {session_id!r} actor_id={raw!r} is not an integer"
        ) from exc
    if not validate_actor_id(conn, actor_id):
        raise ActorResolutionUnavailable(
            f"harness session {session_id!r} actor_id={actor_id} does not "
            "match any actors row"
        )
    return actor_id


def resolve_actor_for_caller(
    conn: Any,
    explicit_actor_id: Optional[int],
    *,
    session_id: Optional[str] = None,
) -> int:
    """Resolve explicit actor, else the calling session's bound actor."""
    if explicit_actor_id is not None:
        if not validate_actor_id(conn, int(explicit_actor_id)):
            from yoke_core.domain.path_claims import InvalidActor

            raise InvalidActor(f"actor_id {explicit_actor_id} does not exist")
        return int(explicit_actor_id)

    actor_id = _session_actor_id(conn, (session_id or "").strip())
    if actor_id is None:
        actor_id = _session_actor_id(conn, _current_session_id())
    if actor_id is not None:
        return actor_id

    raise ActorResolutionUnavailable(
        "the calling session has no bound actor; pass --actor explicitly "
        "or act from a registered harness session"
    )


__all__ = ["ActorResolutionUnavailable", "resolve_actor_for_caller"]
