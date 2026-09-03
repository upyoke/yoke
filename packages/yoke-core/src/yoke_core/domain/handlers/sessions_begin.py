"""Handler for the transport-keyed ``sessions.begin`` function id.

Session establishment is the twin of the operator-debug ``session-begin``
service-client command, exposed as a dispatched function so the ``/yoke do``
bootstrap routes it through the connection-keyed transport (https relay to
the connected server for a prod bootstrap; in-process dispatch for a local
universe). The registration/lane/idempotency core is shared with the
operator-debug command via ``begin_session``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_model_facts import facts_from_mapping

from yoke_core.domain.handlers.sessions_orchestration import (
    _connect_rw,
    _err,
    _session_id,
)


class BeginRequest(BaseModel):
    executor: str
    provider: str
    #: The ask. A caller establishing a session states what it wants to
    #: run; the served columns below are filled only by an attestation.
    requested_model: Optional[str] = None
    requested_reasoning_effort: Optional[str] = None
    requested_context_window_tokens: Optional[int] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    context_window_tokens: Optional[int] = None
    workspace: str
    project_id: int
    mode: str = "wait"
    entrypoint: Optional[str] = None
    executor_version: Optional[str] = None
    machine_id: Optional[str] = None
    native_thread_id: Optional[str] = None
    #: The launch that started this session, when one did. Registration
    #: binds the launching actor from it, so a launched worker acts for
    #: whoever started it rather than for the machine running it.
    launch_id: Optional[str] = None


class BeginResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool


def _bound_actor_id(request: FunctionCallRequest) -> Optional[int]:
    """Return the caller's authenticated actor, when the boundary bound one.

    Over https the HTTP boundary replaces the envelope actor with the
    verified bearer-token actor, so registration binds the authenticated
    principal rather than guessing at the universe's operating actor. In
    process there is no token: a first-time session carries no actor here
    and registration resolves the operating actor itself.
    """
    raw = (request.actor.actor_id or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def handle_begin(request: FunctionCallRequest) -> HandlerOutcome:
    """Register (or idempotently refresh) the caller's session row.

    The project is resolved on the client (the caller ships ``project_id``
    in the payload) so the server never consults its own checkout map for
    the caller's workspace — the resolution that keeps begin correct over
    an https relay.
    """
    try:
        body = BeginRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _err("payload_invalid", f"begin payload invalid: {exc}")
    sid = _session_id(request)
    if not sid:
        return _err("session_required", "session id is required")

    from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
    from yoke_core.domain.sessions import SessionError

    with _connect_rw() as conn:
        try:
            result = begin_session(
                conn,
                session_id=sid,
                executor=body.executor,
                provider=body.provider,
                model_facts=facts_from_mapping(body.model_dump()),
                workspace=body.workspace,
                project_id=body.project_id,
                mode=body.mode,
                entrypoint=body.entrypoint,
                executor_version=body.executor_version,
                machine_id=body.machine_id,
                native_thread_id=body.native_thread_id,
                actor_id=_bound_actor_id(request),
                launch_id=body.launch_id,
            )
        except SessionError as exc:
            return _err(exc.code.lower(), exc.message)
    return HandlerOutcome(result_payload=result)


__all__ = ["BeginRequest", "BeginResponse", "handle_begin"]
