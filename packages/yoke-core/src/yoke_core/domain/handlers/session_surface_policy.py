"""Registered handlers for per-machine surface disable marks."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.surface_policy import (
    SurfacePolicyClearRequest,
    SurfacePolicyListRequest,
    SurfacePolicySetRequest,
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


def _project_id(conn, project: str) -> int:
    from yoke_core.domain.project_identity import resolve_project_id

    return int(resolve_project_id(conn, project))


def _authorize(conn, request: FunctionCallRequest, project: str, action: str) -> None:
    from yoke_core.domain.session_operator_authority import (
        require_operator_or_steering_authority,
    )

    require_operator_or_steering_authority(
        conn,
        actor_id=numeric_actor_id(request),
        caller_session_id=str(request.actor.session_id or "").strip(),
        project_id=_project_id(conn, project),
        action=action,
        error_code="SURFACE_POLICY_AUTHORITY_REQUIRED",
    )


def handle_surface_policy_set(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request):
        return invalid
    if invalid := require_top_level_message_actor(request):
        return invalid
    body = parse(SurfacePolicySetRequest, request)
    if isinstance(body, HandlerOutcome):
        return body
    from yoke_core.domain.session_surface_policy import SurfacePolicyError, set_mark

    conn = open_connection()
    try:
        _authorize(conn, request, body.project, "Surface disable")
        mark = set_mark(
            conn,
            machine_id=body.machine_id,
            surface=body.surface,
            reason=body.reason,
            evidence=body.evidence,
            actor_id=numeric_actor_id(request),
            session_id=str(request.actor.session_id or "").strip() or None,
        )
        conn.commit()
        return HandlerOutcome(result_payload={"mark": mark})
    except (SessionError, SurfacePolicyError) as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


def handle_surface_policy_clear(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request):
        return invalid
    if invalid := require_top_level_message_actor(request):
        return invalid
    body = parse(SurfacePolicyClearRequest, request)
    if isinstance(body, HandlerOutcome):
        return body
    from yoke_core.domain.session_surface_policy import SurfacePolicyError, clear_mark

    conn = open_connection()
    try:
        _authorize(conn, request, body.project, "Surface enable")
        mark = clear_mark(
            conn,
            machine_id=body.machine_id,
            surface=body.surface,
            actor_id=numeric_actor_id(request),
        )
        conn.commit()
        return HandlerOutcome(result_payload={"mark": mark})
    except (SessionError, SurfacePolicyError) as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


def handle_surface_policy_list(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request):
        return invalid
    body = parse(SurfacePolicyListRequest, request)
    if isinstance(body, HandlerOutcome):
        return body
    from yoke_core.domain.session_surface_policy import list_marks

    conn = open_connection()
    try:
        marks = list_marks(
            conn,
            machine_id=body.machine_id,
            surface=body.surface,
            include_cleared=body.include_cleared,
        )
        return HandlerOutcome(result_payload={"marks": marks, "count": len(marks)})
    except Exception as exc:
        return domain_error(exc)
    finally:
        conn.close()


__all__ = [
    "handle_surface_policy_clear",
    "handle_surface_policy_list",
    "handle_surface_policy_set",
]
