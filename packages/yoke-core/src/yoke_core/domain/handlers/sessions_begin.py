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

from yoke_core.domain.handlers.sessions_orchestration import (
    _connect_rw,
    _err,
    _session_id,
)


class BeginRequest(BaseModel):
    executor: str
    provider: str
    model: str
    workspace: str
    project_id: int
    mode: str = "wait"
    entrypoint: Optional[str] = None


class BeginResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool


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
                model=body.model,
                workspace=body.workspace,
                project_id=body.project_id,
                mode=body.mode,
                entrypoint=body.entrypoint,
            )
        except SessionError as exc:
            return _err(exc.code.lower(), exc.message)
    return HandlerOutcome(result_payload=result)


__all__ = ["BeginRequest", "BeginResponse", "handle_begin"]
