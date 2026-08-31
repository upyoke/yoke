"""Hook-evaluate route — ``POST /v1/hooks/evaluate``.

Serves the server half of the relay split — every policy outside
``LOCAL_STATE_POLICIES`` — to machines whose project-local hooks run
``yoke hook evaluate <event>`` over https transport (the relay client
evaluates the local-state subset itself and composes the verdicts). Auth
is enforced by the app-level bearer-token middleware like every other
``/v1`` route; the verified token's actor binds to the ``harness_sessions``
row at relayed ensure-register. The wire contract is frozen: see
:mod:`yoke_harness.hooks.relay` (client) and
:mod:`yoke_core.hooks.remote_entry` (evaluation).
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from yoke_contracts.session_model_facts import facts_from_mapping
from yoke_core.api.http_auth import require_auth_context
from yoke_core.api.observability import record_counter, record_histogram
from yoke_core.domain.execution_provenance import collect_execution_provenance
from yoke_core.domain.hook_runner_deadline import resolve_total_timeout_ms
from yoke_core.domain.session_ambient_identity import (
    is_conversation_shaped_session_id,
)
from yoke_core.hooks.remote_entry import evaluate_remote
from yoke_core.api.routes.hooks_denial_audit import router as _denial_audit_router


router = APIRouter()

# Version tag for the hook-evaluate wire contract (request and response).
HOOK_WIRE_SCHEMA = 1


class HookEvaluateRequest(BaseModel):
    """Frozen request contract for one hook evaluation."""

    hook_schema: int = HOOK_WIRE_SCHEMA
    event_name: str
    stdin: str = ""
    executor: str = "claude"
    agent_type: Optional[str] = None
    entrypoint: Optional[str] = None
    #: Provider-attested served facts, resolved on the client because only
    #: that machine can read the harness artifact.
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    context_window_tokens: Optional[int] = None
    #: The session's stated ask, resolved from the client's launch env.
    requested_model: Optional[str] = None
    requested_reasoning_effort: Optional[str] = None
    requested_context_window_tokens: Optional[int] = None
    execution_lane: Optional[str] = None
    project_id: Optional[int] = None
    executor_version: Optional[str] = None
    machine_id: Optional[str] = None
    payload_extra: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: Optional[int] = None
    execution_provenance: dict[str, Any] = Field(default_factory=dict)


class HookEvaluateResponse(BaseModel):
    """Frozen response contract: relayed stdout/exit_code + the structured
    ``outcome`` (``completed | timeout | denied``) the client's verdict
    composition keys on."""

    hook_schema: int = HOOK_WIRE_SCHEMA
    stdout: str
    exit_code: int
    wait_ms: int
    degraded: List[str]
    outcome: str


@router.post("/hooks/evaluate")
def post_hooks_evaluate(
    http_request: Request, request: HookEvaluateRequest,
) -> JSONResponse:
    """Evaluate one hook event server-side and relay the rendered decision."""
    stamped = _refuse_conversation_shaped(request)
    if stamped is not None:
        return stamped
    if request.hook_schema != HOOK_WIRE_SCHEMA:
        # An unknown schema must not be half-interpreted; the client treats
        # any non-200 as fail-open no-op, which is the safe degradation.
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "UNSUPPORTED_HOOK_SCHEMA",
                    "message": (
                        f"hook_schema {request.hook_schema} is not supported "
                        f"(server speaks {HOOK_WIRE_SCHEMA})"
                    ),
                }
            },
        )
    deadline_ms = (
        request.deadline_ms
        if request.deadline_ms is not None and request.deadline_ms > 0
        else resolve_total_timeout_ms()
    )
    auth = require_auth_context(http_request)
    auth_error = _authorize_project(auth.actor_id, request)
    if auth_error is not None:
        return auth_error
    result = evaluate_remote(
        event_name=request.event_name,
        stdin_data=request.stdin,
        executor=request.executor,
        agent_type=request.agent_type,
        entrypoint=request.entrypoint,
        model_facts=facts_from_mapping(request.model_dump()),
        execution_lane=request.execution_lane,
        project_id=request.project_id,
        executor_version=request.executor_version,
        machine_id=request.machine_id,
        payload_extra=request.payload_extra,
        deadline_ms=deadline_ms,
        actor_id=auth.actor_id,
    )
    if result.outcome == "denied":
        skew_reason = _guard_revision_skew_reason(request)
        if skew_reason:
            _emit_route_denial("guard_version_skew", skew_reason, request)
    attributes = {"event": request.event_name, "outcome": result.outcome}
    record_histogram("yoke.hook.wait_ms", result.wait_ms, attributes=attributes)
    record_counter("yoke.hook.requests", attributes=attributes)
    return JSONResponse(
        content=_with_provenance(
            HookEvaluateResponse(
                stdout=result.stdout,
                exit_code=result.exit_code,
                wait_ms=result.wait_ms,
                degraded=list(result.degraded),
                outcome=result.outcome,
            ).model_dump()
        )
    )


def _with_provenance(content: dict[str, Any]) -> dict[str, Any]:
    content["execution_provenance"] = collect_execution_provenance()
    return content


def _stdin_payload(request: HookEvaluateRequest) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(request.stdin) if request.stdin else {}
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


_UNKNOWN_REVISIONS = frozenset({"", "unknown"})


def _guard_revision_skew_reason(request: HookEvaluateRequest) -> str:
    """Explain a client/server guard-revision mismatch on this denial, or "".

    A denial rendered under skew may be running server code that predates
    (or postdates) the guard that produced it, so this comparison — not any
    single guard's own emission — is what makes the mismatch itself durable.
    """
    client_revision = str(request.execution_provenance.get("source_sha") or "").strip().lower()
    server_revision = str(collect_execution_provenance().get("source_sha") or "").strip().lower()
    if client_revision in _UNKNOWN_REVISIONS or server_revision in _UNKNOWN_REVISIONS:
        return ""
    if client_revision == server_revision or client_revision.startswith(
        server_revision
    ) or server_revision.startswith(client_revision):
        return ""
    return (
        f"Denial rendered during guard-revision skew: server revision "
        f"{server_revision[:12]} vs client revision {client_revision[:12]}."
    )


def _emit_route_denial(
    check_id: str,
    reason: str,
    request: HookEvaluateRequest,
) -> None:
    """Record HarnessToolCallDenied for a pre-dispatch route refusal.

    Both refusals below return ``outcome="denied"`` before the guard chain
    (``evaluate_remote``) ever runs, so no guard module gets a chance to
    emit — this is the only place that can. Revision pair is the requesting
    client's own reported provenance against this server's, so a denial
    recorded during guard-revision skew still carries both sides.
    """
    try:
        from yoke_core.hooks.denial import emit_denial_event
    except Exception:
        return
    payload = _stdin_payload(request)
    session_id = payload.get("session_id")
    tool_use_id = payload.get("tool_use_id")
    turn_id = payload.get("turn_id") or payload.get("message_id")
    server_revision = collect_execution_provenance().get("source_sha") or ""
    client_revision = request.execution_provenance.get("source_sha") or ""
    try:
        emit_denial_event(
            hook="yoke_core.api.routes.hooks",
            check_id=check_id,
            reason=reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn_id if isinstance(turn_id, str) else "",
            guard_key=check_id,
            mode="deny",
            client_revision=str(client_revision),
            server_revision=str(server_revision),
        )
    except Exception:
        pass


def _refuse_conversation_shaped(request: HookEvaluateRequest) -> JSONResponse | None:
    """Reject relayed payloads whose stamped session id is still a conversation."""
    payload = _stdin_payload(request)
    if payload.get("identity_stamped") is True:
        return None
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sid.strip():
        reason = (
            "Yoke hook relay refused: payload has no stamped, "
            "non-conversation session id."
        )
        _emit_route_denial("conversation_shaped_session", reason, request)
        return JSONResponse(
            content=_with_provenance(
                HookEvaluateResponse(
                    stdout=f"{reason}\n",
                    exit_code=2,
                    wait_ms=0,
                    degraded=[],
                    outcome="denied",
                ).model_dump()
            ),
        )
    if is_conversation_shaped_session_id(payload, session_id=sid):
        reason = "Yoke hook relay refused: session id is still conversation-shaped."
        _emit_route_denial("conversation_shaped_session", reason, request)
        return JSONResponse(
            content=_with_provenance(
                HookEvaluateResponse(
                    stdout=f"{reason}\n",
                    exit_code=2,
                    wait_ms=0,
                    degraded=[],
                    outcome="denied",
                ).model_dump()
            ),
        )
    return None


def _authorize_project(
    actor_id: int,
    request: HookEvaluateRequest,
) -> JSONResponse | None:
    project_id = request.project_id
    if project_id is None:
        reason = (
            "Yoke hook registration denied: this checkout has no "
            "configured project id. Run Yoke setup for this checkout."
        )
        _emit_route_denial("project_authorization", reason, request)
        return JSONResponse(
            content=HookEvaluateResponse(
                stdout=f"{reason}\n",
                exit_code=1,
                wait_ms=0,
                degraded=[],
                outcome="denied",
            ).model_dump(),
        )
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.actor_project_visibility import actor_visible_project_ids

        with db_helpers.connect() as conn:
            visible = actor_visible_project_ids(conn, actor_id) or set()
    except Exception:
        reason = "Yoke hook registration denied: project auth unavailable."
        _emit_route_denial("project_authorization", reason, request)
        return JSONResponse(
            content=HookEvaluateResponse(
                stdout=f"{reason}\n",
                exit_code=1,
                wait_ms=0,
                degraded=[],
                outcome="denied",
            ).model_dump(),
        )
    if int(project_id) in visible:
        return None
    reason = (
        f"Yoke hook registration denied: actor cannot access project {int(project_id)}."
    )
    _emit_route_denial("project_authorization", reason, request)
    return JSONResponse(
        content=HookEvaluateResponse(
            stdout=f"{reason}\n",
            exit_code=1,
            wait_ms=0,
            degraded=[],
            outcome="denied",
        ).model_dump(),
    )


router.include_router(_denial_audit_router)


__all__ = ["HOOK_WIRE_SCHEMA", "router"]
