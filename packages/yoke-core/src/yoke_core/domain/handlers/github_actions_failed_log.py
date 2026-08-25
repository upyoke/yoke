"""Handler for ``github_actions.failed_log`` — failed-step log tail."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.github_actions_identifiers import (
    WorkflowIdentifier,
    WorkflowRunId,
)
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve,
)
from yoke_core.domain.github_actions_run_monitoring import format_failed_log_output


class FailedLogRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    project: str = Field(..., min_length=1)
    run_id: Optional[WorkflowRunId] = None
    workflow: Optional[WorkflowIdentifier] = None
    branch: str = Field("main")
    head_sha: str = Field("")
    tail_lines: int = Field(50, ge=1)

    @model_validator(mode="after")
    def _requires_run_selector(self) -> "FailedLogRequest":
        if not str(self.run_id or "").strip() and not str(self.workflow or "").strip():
            raise ValueError("run_id or workflow is required")
        return self


class FailedLogResponse(BaseModel):
    run_id: str
    output: str
    truncated: bool = False


def _resolve_run_id(
    payload: FailedLogRequest,
    *,
    token: str,
) -> tuple[str | None, HandlerOutcome | None]:
    if str(payload.run_id or "").strip():
        return str(payload.run_id), None

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import latest_workflow_run

    try:
        run = latest_workflow_run(
            payload.repo,
            str(payload.workflow),
            branch=payload.branch,
            head_sha=payload.head_sha,
            token=token,
        )
    except RestTransportError as exc:
        return None, _transport_failed(f"workflow run lookup failed: {exc}")

    if not run or not run.get("id"):
        return None, _transport_failed(
            "no workflow run found for the requested selector",
        )
    return str(run["id"]), None


def handle_failed_log(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, error = _validate_and_resolve(
        request,
        FailedLogRequest,
        "github_actions.failed_log",
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    if error is not None:
        return error

    run_id, resolve_error = _resolve_run_id(payload, token=token)
    if resolve_error is not None:
        return resolve_error
    assert run_id is not None

    from yoke_core.domain.gh_rest_transport import RestAuthError, RestTransportError
    from yoke_core.domain.github_actions_logs import fetch_failed_log

    try:
        per_job = fetch_failed_log(payload.repo, run_id, token=token)
    except RestAuthError as exc:
        return _transport_failed(
            f"GitHub auth failure fetching logs for run {run_id}: {exc}",
        )
    except RestTransportError as exc:
        return _transport_failed(f"failed to fetch logs for run {run_id}: {exc}")

    formatted = format_failed_log_output(per_job, tail_lines=payload.tail_lines)
    if formatted is None:
        return _transport_failed("(no failed-step output captured)")

    output, truncated = formatted
    return HandlerOutcome(
        result_payload=FailedLogResponse(
            run_id=run_id,
            output=output,
            truncated=truncated,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github_actions.failed_log",
        "handler": handle_failed_log,
        "request_model": FailedLogRequest,
        "response_model": FailedLogResponse,
        "stability": "stable",
        "owner_module": __name__,
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "FailedLogRequest",
    "FailedLogResponse",
    "REGISTRATIONS",
    "handle_failed_log",
]
