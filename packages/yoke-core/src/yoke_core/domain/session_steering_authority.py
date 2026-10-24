"""Steering-seat authority for direct session-control actions."""

from __future__ import annotations

from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain import db_backend
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_queries import _row_to_dict


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


def steering_authority_message(project: int | str) -> str:
    """Name the required seat and its reachable recovery route."""
    return compose_refusal(
        f"requires a live steering seat for project {project}.",
        recovery=f'yoke claims steering acquire --project {project} --reason "<intent>", or route via yoke say --steering.',
    )


def covering_session_seat(
    conn: Any, *, caller_session_id: str, target: dict[str, Any]
) -> dict[str, Any] | None:
    """Return this live session's seat covering the targeted work."""
    from yoke_core.domain.steering_scope_coverage import covering_claims

    return next(
        (
            seat
            for seat in covering_claims(conn, target)
            if str(seat["session_id"]) == caller_session_id
        ),
        None,
    )


def require_steering_authority(
    conn: Any,
    *,
    caller_session_id: str,
    project_id: int,
    action: str = "Session control",
    error_code: str = "SESSION_CONTROL_AUTHORITY_REQUIRED",
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require a live steering seat covering the project or document scope."""
    seat = covering_session_seat(
        conn,
        caller_session_id=caller_session_id,
        target=target if target is not None else {"project_id": int(project_id)},
    )
    if seat is None:
        raise SessionError(
            error_code, f"{action} {steering_authority_message(project_id)}"
        )
    return seat


def require_any_steering_seat(
    conn: Any, *, caller_session_id: str, action: str, error_code: str
) -> dict[str, Any]:
    """Require the caller to hold a live steering seat on any project.

    Org-wide session control: a seat on one project acts on sessions in
    every project, including one holding another project's seat.
    """
    from yoke_core.domain.steering_scope_coverage import live_steering_claims

    seat = next(
        (
            claim
            for claim in live_steering_claims(conn)
            if str(claim["session_id"]) == caller_session_id
        ),
        None,
    )
    if seat is None:
        raise SessionError(
            error_code,
            compose_refusal(
                f"{action} requires a live steering seat on any project.",
                recovery=(
                    'yoke claims steering acquire --project PROJECT --reason "<intent>", or '
                    "route via yoke say --steering."
                ),
            ),
        )
    return seat


def require_operator_seat(
    conn: Any, *, caller_session_id: str | None, project_id: int, action: str
) -> dict[str, Any]:
    """Gate an operator-only command on the caller's live covering seat.

    Actor kind and session mode never decide; a session-less call has no
    seat and refuses with the same ``steering_seat_required`` recovery.
    """
    return require_steering_authority(
        conn,
        caller_session_id=caller_session_id or "",
        project_id=project_id,
        action=action,
        error_code="steering_seat_required",
    )


__all__ = [
    "covering_session_seat",
    "require_any_steering_seat",
    "require_operator_seat",
    "require_steering_authority",
    "session_control_target",
    "steering_authority_message",
]
