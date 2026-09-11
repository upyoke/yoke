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

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.session_model_facts import facts_from_mapping
from yoke_core.api.http_auth import require_auth_context
from yoke_core.api.observability import record_counter, record_histogram
from yoke_core.domain.execution_provenance import collect_execution_provenance
from yoke_core.domain.hook_runner_deadline import resolve_total_timeout_ms
from yoke_core.hooks.relayed_session_identity import (
    refusal_text,
    stamped_identity_refusal,
)
from yoke_core.hooks.remote_entry import evaluate_remote
from yoke_core.hooks.session_model_attestation_write import confirmed_served_model
from yoke_core.api.routes.hooks_denial_audit import router as _denial_audit_router
from yoke_core.api.routes.hooks_wire_contract import (
    HOOK_WIRE_SCHEMA,
    HookEvaluateRequest,
    HookEvaluateResponse,
)
from yoke_core.api.routes.hook_observations import router as _observation_router


router = APIRouter()


@router.post("/hooks/evaluate")
def post_hooks_evaluate(
    http_request: Request,
    request: HookEvaluateRequest,
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
        usage_totals=request.usage_totals,
        execution_lane=request.execution_lane,
        project_id=request.project_id,
        executor_version=request.executor_version,
        machine_id=request.machine_id,
        native_thread_id=request.native_thread_id,
        payload_extra=request.payload_extra,
        deadline_ms=deadline_ms,
        actor_id=auth.actor_id,
    )
    if result.outcome == "denied":
        skew_reason = _guard_revision_skew_reason(request)
        if skew_reason:
            audit = result.denial_audit
            _emit_route_denial(
                audit.get("check_id") or "hook_policy_denial",
                audit.get("reason") or "Hook policy denied.",
                request,
                hook=audit.get("hook") or "yoke_core.api.routes.hooks",
                guard_version_skew=skew_reason,
            )
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
                model_confirmation=confirmed_served_model(
                    _stdin_payload(request).get("session_id"), request.model
                ),
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
    client_revision = (
        str(request.execution_provenance.get("source_sha") or "").strip().lower()
    )
    server_revision = (
        str(collect_execution_provenance().get("source_sha") or "").strip().lower()
    )
    if client_revision in _UNKNOWN_REVISIONS or server_revision in _UNKNOWN_REVISIONS:
        return ""
    if (
        client_revision == server_revision
        or client_revision.startswith(server_revision)
        or server_revision.startswith(client_revision)
    ):
        return ""
    return (
        f"Denial rendered during guard-revision skew: server revision "
        f"{server_revision[:12]} vs client revision {client_revision[:12]}."
    )


def _emit_route_denial(
    check_id: str,
    reason: str,
    request: HookEvaluateRequest,
    *,
    hook: str = "yoke_core.api.routes.hooks",
    guard_version_skew: str = "",
) -> None:
    """Record a route refusal or annotate a chain denial during skew.

    Pre-dispatch refusals have no guard emitter. A skew annotation after
    dispatch preserves the runner-reported hook/check/reason as the denial.
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
            hook=hook,
            check_id=check_id,
            reason=reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn_id if isinstance(turn_id, str) else "",
            guard_key=check_id,
            mode="deny",
            client_revision=str(client_revision),
            server_revision=str(server_revision),
            guard_version_skew=guard_version_skew,
        )
    except Exception:
        pass


def _refuse_conversation_shaped(request: HookEvaluateRequest) -> JSONResponse | None:
    """Reject relayed payloads whose stamped session id is still a conversation.

    The predicate is shared with the observation-batch route so the two
    cannot drift back into refusing each other's payloads.
    """
    reason_key = stamped_identity_refusal(_stdin_payload(request))
    if reason_key is None:
        return None
    reason = f"Yoke hook relay refused: {refusal_text(reason_key)}."
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


def _authorize_project(
    actor_id: int,
    request: HookEvaluateRequest,
) -> JSONResponse | None:
    project_id = request.project_id
    if project_id is None:
        reason = (
            "Yoke hook registration denied: this checkout has no "
            "configured project id. Run Yoke setup for this checkout if it "
            "is a real project. For an isolated scratch/canary checkout, do "
            "not register it in the shared machine config — set "
            f"{machine_config_runtime.CONFIG_FILE_ENV} to a throwaway config "
            "file for this process tree and register the checkout there "
            "instead, so shared checkout routing for the real project is "
            "never touched."
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
router.include_router(_observation_router)


__all__ = ["HOOK_WIRE_SCHEMA", "router"]
