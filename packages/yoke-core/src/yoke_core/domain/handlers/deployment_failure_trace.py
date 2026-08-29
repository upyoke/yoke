"""Read-only handler for terminal deployment failure diagnostics."""

from __future__ import annotations

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error


class DeploymentFailureTraceRequest(BaseModel):
    pass


class FailureChainEntry(BaseModel):
    repo: str = Field(..., min_length=3)
    run_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    failed_job: str = ""


class DeploymentFailureTraceResponse(BaseModel):
    deployment_run_id: str
    stage: str
    complete: bool
    chain: list[FailureChainEntry]
    terminal_job: str = ""
    terminal_error: str = ""
    stop_reason: str = ""
    recovery: str = ""


def _actor_id(request: FunctionCallRequest) -> int | None:
    raw = request.actor.actor_id if request.actor else None
    text = str(raw or "").strip()
    return int(text) if text.isdigit() else None


def _run_id(request: FunctionCallRequest) -> str | HandlerOutcome:
    value = request.target.deployment_run_id
    if isinstance(value, str) and value.strip():
        return value.strip()
    return error(
        "target_invalid",
        "deployment_runs.failure_trace requires target.deployment_run_id",
        jsonpath="$.target.deployment_run_id",
    )


def handle_deployment_failure_trace(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = _run_id(request)
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id

    from yoke_core.domain.deployment_failure_trace_runtime import (
        trace_deployment_failure,
    )

    try:
        result = trace_deployment_failure(
            resolved_run_id,
            actor_id=_actor_id(request),
        )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.target.workflow_run_id")
    except PermissionError as exc:
        return error("permission_denied", str(exc))
    except ValueError as exc:
        return error("invalid_state", str(exc))
    except Exception as exc:
        return error("failure_trace_failed", str(exc))
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "DeploymentFailureTraceRequest",
    "DeploymentFailureTraceResponse",
    "FailureChainEntry",
    "handle_deployment_failure_trace",
]
