"""Registered read-back of the calling session's resolved identity.

The handler reads stored identity facts and projects the current execution
level from the session's model and effort. It also reports the checkpoint
budget and whether a Yoke relay started this session as a headless command.
A caller that cannot reach the authority receives a refusal with recovery.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain.handlers.sessions_orchestration import (
    _connect_rw,
    _err,
    _session_id,
)


class IdentityRequest(BaseModel):
    pass


class IdentityResponse(BaseModel):
    session_id: str
    executor: str
    executor_surface: Optional[str] = None
    provider: Optional[str] = None
    #: Provider-attested served truth; null until something attests it.
    model: Optional[str] = None
    #: The launch request. A caller showing this where ``model`` is null
    #: must say it is showing a request.
    requested_model: Optional[str] = None
    execution_level: Optional[str] = None
    level_label: Optional[str] = None
    level_reason: Optional[str] = None
    workspace: Optional[str] = None
    project_id: Optional[int] = None
    org_id: Optional[int] = None
    scope_kind: str
    project_slug: Optional[str] = None
    actor_id: Optional[int] = None
    actor_label: Optional[str] = None
    mode: Optional[str] = None
    max_chain_steps: int
    #: True when a Yoke relay started this session as a headless command.
    #: Such a session cannot be prompted again inside its own turn, so a
    #: caller that would otherwise block on a long wait hands the work to a
    #: durable record and stops instead.
    relay_launched: bool = False


def _project_slug(conn: Any, project_id: Optional[int]) -> Optional[str]:
    if project_id is None:
        return None
    from yoke_core.domain.sessions_identity_read import _p

    row = conn.execute(
        f"SELECT slug FROM projects WHERE id = {_p(conn)}",
        (project_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _actor_label(conn: Any, actor_id: Optional[int]) -> Optional[str]:
    if actor_id is None:
        return None
    from yoke_core.domain.actors import ActorError, actor_name

    try:
        return actor_name(conn, actor_id)
    except ActorError:
        return f"actor {actor_id}"


def _max_chain_steps() -> int:
    from yoke_core.api.session_chain_policy import get_max_chain_steps
    from yoke_core.api.service_client_shared import _get_config_path

    return get_max_chain_steps(_get_config_path())


def handle_identity(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the calling session's stored identity and checkpoint budget."""
    sid = _session_id(request)
    if not sid:
        return _err("session_required", "session id is required")

    from yoke_core.domain.session_relay_launch_context import (
        session_was_relay_launched,
    )
    from yoke_core.domain.sessions import SessionError
    from yoke_core.domain.sessions_ended_recovery import session_ended_message
    from yoke_core.domain.sessions_identity_read import resolve_session_identity

    with _connect_rw() as conn:
        try:
            identity = resolve_session_identity(conn, sid)
        except SessionError as exc:
            return _err(exc.code.lower(), exc.message)
        if identity.ended_at is not None:
            return _err("session_ended", session_ended_message(conn, sid))

        payload: Dict[str, Any] = {
            "session_id": identity.session_id,
            "executor": identity.executor,
            "executor_surface": identity.executor_surface,
            "provider": identity.provider,
            "model": identity.model or None,
            "requested_model": identity.requested_model or None,
            "execution_level": identity.execution_level,
            "level_label": identity.level_label,
            "level_reason": identity.level_reason,
            "workspace": identity.workspace,
            "project_id": identity.project_id,
            "org_id": identity.org_id,
            "scope_kind": identity.scope_kind,
            "project_slug": _project_slug(conn, identity.project_id),
            "actor_id": identity.actor_id,
            "actor_label": _actor_label(conn, identity.actor_id),
            "mode": identity.mode,
            "max_chain_steps": _max_chain_steps(),
            "relay_launched": session_was_relay_launched(conn, sid),
        }
    return HandlerOutcome(result_payload=payload)


__all__ = ["IdentityRequest", "IdentityResponse", "handle_identity"]
