"""Operator-only opening of one stage private-route qualification grant."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationOpenRequest,
)
from yoke_contracts.session_control.teaching import FLEET_OWNERSHIP_GUIDANCE
from yoke_contracts.session_execution import SUBAGENT_EXECUTION_PAYLOAD_KEY


def _failure(code: str, message: str, path: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=path),
    )


def handle_qualification_open(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _failure("target_invalid", "qualification requires a global target")
    if request.options.get(SUBAGENT_EXECUTION_PAYLOAD_KEY) is True:
        return _failure(
            "subagent_qualification_forbidden",
            FLEET_OWNERSHIP_GUIDANCE,
            f"$.options.{SUBAGENT_EXECUTION_PAYLOAD_KEY}",
        )
    try:
        payload = PrivateRouteQualificationOpenRequest.model_validate(
            request.payload or {}
        )
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    raw_actor = str(request.actor.actor_id or "").strip()
    session_id = str(request.actor.session_id or "").strip()
    if not raw_actor.isdigit() or not session_id:
        return _failure(
            "operator_identity_required",
            "a verified operator actor and session are required",
        )
    from yoke_core.domain.actor_permissions import (
        PERM_PROJECT_ADMIN,
        permission_decision,
    )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.session_control_request_identity import (
        registered_request_session_id,
    )
    from yoke_core.domain.session_private_route_qualification import (
        PrivateRouteQualificationError,
        open_qualification_grant,
    )

    conn = connect()
    try:
        project_id = resolve_project_id(conn, payload.project)
        actor_id = int(raw_actor)
        if registered_request_session_id(conn, session_id) is None:
            return _failure(
                "operator_session_unregistered",
                "qualification requires a registered operator session",
            )
        if not permission_decision(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission_key=PERM_PROJECT_ADMIN,
        ).allowed:
            return _failure(
                "permission_denied",
                "project administrator permission is required",
            )
        grant = open_qualification_grant(
            conn,
            project_id=project_id,
            sender_session_id=session_id,
            operator_actor_id=actor_id,
            scope=payload.scope(),
        )
        return HandlerOutcome(result_payload={"grant": grant.model_dump(mode="json")})
    except (LookupError, PrivateRouteQualificationError) as exc:
        conn.rollback()
        return _failure(getattr(exc, "code", "project_not_found"), str(exc))
    except Exception as exc:
        conn.rollback()
        return _failure("qualification_open_failed", str(exc))
    finally:
        conn.close()


__all__ = ["handle_qualification_open"]
