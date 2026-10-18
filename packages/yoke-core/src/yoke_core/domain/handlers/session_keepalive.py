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
    """Return a locked target once its owner or scope policy allows keepalive."""
    from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
    from yoke_core.domain.session_scope_identity import (
        actor_may_operate_session,
        session_scope_of,
    )
    from yoke_core.domain.session_message_types import SessionMessageError
    from yoke_core.domain.session_steering_authority import session_control_target

    target = session_control_target(conn, session_id)
    if not actor_may_operate_session(
        conn,
        actor_id=numeric_actor_id(request),
        scope=session_scope_of(target),
        session_actor_id=target.get("actor_id"),
        permission_key=PERM_ITEMS_WRITE,
    ):
        raise SessionMessageError(
            "unauthorized_target",
            "Session keepalive is not authorized for this actor. Recovery: use an "
            "authorized connection or ask the project owner or org admin for access.",
        )
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
