"""Operator and steering authority for direct session-control actions."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_queries import _row_to_dict
from yoke_core.domain.work_claim_targets import make_steering_target


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def session_control_target(conn: Any, session_id: str) -> dict[str, Any]:
    """Lock and return one target session, or raise a typed not-found result."""
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id = {_p(conn)}{suffix}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    return _row_to_dict(row)


def require_operator_or_steering_authority(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str,
    project_id: int,
    action: str = "Session control",
    error_code: str = "SESSION_CONTROL_AUTHORITY_REQUIRED",
) -> str:
    """Require a live actor-owned operator session or project steering claim."""
    caller = conn.execute(
        f"SELECT actor_id,mode,ended_at,terminated_at FROM harness_sessions "
        f"WHERE session_id = {_p(conn)}",
        (caller_session_id,),
    ).fetchone()
    if caller is None or caller["ended_at"] is not None:
        raise SessionError(
            error_code,
            f"{action} requires a live operator or project steering session.",
        )
    if caller["actor_id"] is None or int(caller["actor_id"]) != int(actor_id):
        raise SessionError(
            error_code,
            "The verified actor does not own the calling session.",
        )
    if str(caller["mode"] or "") == "operator":
        return "operator"
    target = make_steering_target(int(project_id))
    steering = conn.execute(
        "SELECT id FROM work_claims WHERE session_id = "
        + _p(conn)
        + " AND target_kind = "
        + _p(conn)
        + " AND scope = "
        + _p(conn)
        + " AND released_at IS NULL",
        (caller_session_id, "steering", target.scope_json()),
    ).fetchone()
    if steering is not None:
        return "steering"
    raise SessionError(
        error_code,
        f"{action} requires operator mode or the active steering claim "
        f"for project {project_id}.",
    )


__all__ = [
    "require_operator_or_steering_authority",
    "session_control_target",
]
