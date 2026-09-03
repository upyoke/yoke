"""Registered handlers for holding and releasing a session keep-alive."""

from __future__ import annotations

from typing import Any, Dict

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.keepalive import (
    SessionKeepaliveHoldRequest,
    SessionKeepaliveReleaseRequest,
)
from yoke_core.domain.handlers.session_messages_common import (
    domain_error,
    failure,
    numeric_actor_id,
    open_connection,
    parse,
    require_global,
    require_top_level_message_actor,
)
from yoke_core.domain.sessions_analytics import SessionError


def _authorized_target(conn: Any, request: FunctionCallRequest, session_id: str):
    """Return the target row once the caller may operate its project.

    Holding another session alive is a milder act than terminating it, so
    it takes the ordinary project membership messaging and waking take.
    The decision itself comes from the one session-action authority the
    dispatcher also applies, so a caller reaching this handler by another
    route reads the same refusal rather than a second wording of it.
    """
    from yoke_core.domain.session_action_authority import authorize_session_action
    from yoke_core.domain.session_message_types import SessionMessageError
    from yoke_core.domain.session_operator_authority import session_control_target

    target = session_control_target(conn, session_id)
    project_id = target.get("project_id")
    if project_id is None:
        raise SessionMessageError(
            "unauthorized_target",
            f"Session '{session_id}' belongs to no project, so no actor can "
            "be authorized to hold it alive.",
        )
    decision = authorize_session_action(
        conn,
        actor_id=numeric_actor_id(request),
        function_id=request.function,
        project_id=int(project_id),
        target=target,
    )
    if not decision.allowed:
        raise SessionMessageError("unauthorized_target", decision.message)
    return target


def _held(session_id: str, session: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "held": True,
        "keepalive_until": session.get("keepalive_until"),
        "keepalive_reason": session.get("keepalive_reason"),
        "session": session,
    }


def handle_session_keepalive_hold(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request):
        return invalid
    if invalid := require_top_level_message_actor(request):
        return invalid
    body = parse(SessionKeepaliveHoldRequest, request)
    if isinstance(body, HandlerOutcome):
        return body

    from yoke_core.domain.session_keepalive import hold_session_keepalive

    conn = open_connection()
    try:
        _authorized_target(conn, request, body.session_id)
        session = hold_session_keepalive(
            conn,
            body.session_id,
            seconds=body.seconds,
            reason=body.reason,
        )
        return HandlerOutcome(result_payload=_held(body.session_id, session))
    except SessionError as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


def handle_session_keepalive_release(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request):
        return invalid
    if invalid := require_top_level_message_actor(request):
        return invalid
    body = parse(SessionKeepaliveReleaseRequest, request)
    if isinstance(body, HandlerOutcome):
        return body

    from yoke_core.domain.session_keepalive import release_session_keepalive

    conn = open_connection()
    try:
        _authorized_target(conn, request, body.session_id)
        released = release_session_keepalive(conn, body.session_id)
        return HandlerOutcome(
            result_payload={
                "session_id": body.session_id,
                "held": False,
                "released": released,
            }
        )
    except SessionError as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


__all__ = [
    "handle_session_keepalive_hold",
    "handle_session_keepalive_release",
]
