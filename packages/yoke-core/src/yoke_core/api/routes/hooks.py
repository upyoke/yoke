"""Hook-evaluate route — ``POST /v1/hooks/evaluate``.

Serves the server half of the relay split — every policy outside
``LOCAL_STATE_POLICIES`` — to machines whose project-local hooks run
``yoke hook evaluate <event>`` over https transport (the relay client
evaluates the local-state subset itself and composes the verdicts). Auth
is enforced by the app-level bearer-token middleware like every other
``/v1`` route; the verified token's actor binds to the ``harness_sessions``
row at relayed ensure-register. The wire contract is frozen: see
:mod:`yoke_cli.hooks.relay` (client) and
:mod:`runtime.harness.hook_runner.remote_entry` (evaluation).
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from yoke_core.api.http_auth import require_auth_context
from yoke_core.api.observability import record_counter, record_histogram
from runtime.harness.hook_runner.deadline import resolve_total_timeout_ms
from runtime.harness.hook_runner.remote_entry import evaluate_remote


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
    model: Optional[str] = None
    execution_lane: Optional[str] = None
    project_id: Optional[int] = None
    payload_extra: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: Optional[int] = None


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
    auth_error = _authorize_project(auth.actor_id, request.project_id)
    if auth_error is not None:
        return auth_error
    result = evaluate_remote(
        event_name=request.event_name,
        stdin_data=request.stdin,
        executor=request.executor,
        agent_type=request.agent_type,
        entrypoint=request.entrypoint,
        model=request.model,
        execution_lane=request.execution_lane,
        project_id=request.project_id,
        payload_extra=request.payload_extra,
        deadline_ms=deadline_ms,
        actor_id=auth.actor_id,
    )
    attributes = {"event": request.event_name, "outcome": result.outcome}
    record_histogram("yoke.hook.wait_ms", result.wait_ms, attributes=attributes)
    record_counter("yoke.hook.requests", attributes=attributes)
    return JSONResponse(
        content=HookEvaluateResponse(
            stdout=result.stdout,
            exit_code=result.exit_code,
            wait_ms=result.wait_ms,
            degraded=list(result.degraded),
            outcome=result.outcome,
        ).model_dump()
    )


def _authorize_project(actor_id: int, project_id: Optional[int]) -> JSONResponse | None:
    if project_id is None:
        return JSONResponse(
            content=HookEvaluateResponse(
                stdout=(
                    "Yoke hook registration denied: this checkout has no "
                    "configured project id. Run Yoke setup for this checkout.\n"
                ),
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
        return JSONResponse(
            content=HookEvaluateResponse(
                stdout="Yoke hook registration denied: project auth unavailable.\n",
                exit_code=1,
                wait_ms=0,
                degraded=[],
                outcome="denied",
            ).model_dump(),
        )
    if int(project_id) in visible:
        return None
    return JSONResponse(
        content=HookEvaluateResponse(
            stdout=(
                f"Yoke hook registration denied: actor cannot access project "
                f"{int(project_id)}.\n"
            ),
            exit_code=1,
            wait_ms=0,
            degraded=[],
            outcome="denied",
        ).model_dump(),
    )


__all__ = ["HOOK_WIRE_SCHEMA", "router"]
