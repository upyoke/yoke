"""GitHub Actions workflow queries and function registrations.

These handlers keep GitHub App private-key authority inside the control plane.
Remote deploy clients send their scoped Yoke bearer token to the function-call
API; the handler resolves the project's App installation token and performs one
bounded GitHub REST operation. Dispatch-specific models and handlers live in
:mod:`github_actions_workflow_dispatch`; waiting and retry backoff stay
client-side.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers.github_actions_workflow_dispatch import (
    OWNER_MODULE as DISPATCH_OWNER_MODULE,
    WorkflowDispatchOnceRequest,
    WorkflowDispatchRequest,
    WorkflowDispatchResponse,
    handle_workflow_dispatch,
    handle_workflow_dispatch_once,
)
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve,
)
from yoke_core.domain.github_actions_identifiers import (
    WorkflowIdentifier,
    WorkflowRunId,
)


class WorkflowFindRunRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    workflow: WorkflowIdentifier
    project: str = Field(..., min_length=1)
    head_sha: Optional[str] = None
    branch: Optional[str] = None
    event: Optional[str] = None
    exclude_run_id: Optional[str] = None

    @model_validator(mode="after")
    def _requires_selector(self) -> "WorkflowFindRunRequest":
        if not str(self.head_sha or "").strip() and not str(self.branch or "").strip():
            raise ValueError("head_sha or branch is required")
        return self


class WorkflowFindRunResponse(BaseModel):
    found: bool
    run_id: Optional[str] = None
    status: Optional[str] = None
    conclusion: Optional[str] = None
    html_url: Optional[str] = None


class RunJobsCountRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    run_id: WorkflowRunId
    attempt: int = Field(1, ge=1)
    project: str = Field(..., min_length=1)


class RunJobsCountResponse(BaseModel):
    run_id: str
    count: int = Field(..., ge=0)


def _first_run(data: Any, *, exclude_run_id: str = "") -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("workflow-runs response must be an object")
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("workflow-runs response omitted workflow_runs")
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("workflow-runs response contained a malformed run")
        run_id = str(run.get("id") or "")
        if not run_id:
            raise ValueError("workflow-runs response contained a run without id")
        if run_id and run_id != exclude_run_id:
            return run
    return None


def handle_workflow_find_run(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, error = _validate_and_resolve(
        request,
        WorkflowFindRunRequest,
        "github_actions.workflow.find_run",
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    if error is not None:
        return error

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    query = {"per_page": "10" if payload.exclude_run_id else "1"}
    for key, value in (
        ("head_sha", payload.head_sha),
        ("branch", payload.branch),
        ("event", payload.event),
    ):
        if str(value or "").strip():
            query[key] = str(value)
    try:
        data = rest_get(
            f"/repos/{payload.repo}/actions/workflows/{payload.workflow}/runs",
            query=query,
            token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"workflow run lookup failed: {exc}")

    try:
        run = _first_run(
            data,
            exclude_run_id=str(payload.exclude_run_id or ""),
        )
    except ValueError as exc:
        return _transport_failed(str(exc))
    response = WorkflowFindRunResponse(found=run is not None)
    if run is not None:
        response = WorkflowFindRunResponse(
            found=True,
            run_id=str(run.get("id") or "") or None,
            status=str(run.get("status") or "") or None,
            conclusion=str(run.get("conclusion") or "") or None,
            html_url=str(run.get("html_url") or "") or None,
        )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


def handle_run_jobs_count(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, error = _validate_and_resolve(
        request,
        RunJobsCountRequest,
        "github_actions.run.jobs_count",
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    if error is not None:
        return error

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    try:
        data = rest_get(
            f"/repos/{payload.repo}/actions/runs/{payload.run_id}/attempts/"
            f"{payload.attempt}/jobs",
            token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"workflow jobs lookup failed: {exc}")
    if not isinstance(data, dict) or "total_count" not in data:
        return _transport_failed("workflow jobs response omitted total_count")
    raw_count = data.get("total_count")
    if (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or raw_count < 0
    ):
        return _transport_failed(
            "workflow jobs total_count must be a non-negative integer"
        )
    count = raw_count
    return HandlerOutcome(
        result_payload=RunJobsCountResponse(
            run_id=payload.run_id,
            count=count,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github_actions.workflow.dispatch",
        "handler": handle_workflow_dispatch,
        "request_model": WorkflowDispatchRequest,
        "response_model": WorkflowDispatchResponse,
        "stability": "stable",
        "owner_module": DISPATCH_OWNER_MODULE,
        "target_kinds": ["global"],
        "side_effects": ["github_actions_workflow_dispatch"],
        "emitted_event_names": [],
        "guardrails": [
            "project_auth_required",
            "api_token_actor_bound",
            "handler_managed_idempotency",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
    {
        "function_id": "github_actions.workflow.dispatch_once",
        "handler": handle_workflow_dispatch_once,
        "request_model": WorkflowDispatchOnceRequest,
        "response_model": WorkflowDispatchResponse,
        "stability": "stable",
        "owner_module": DISPATCH_OWNER_MODULE,
        "target_kinds": ["global"],
        "side_effects": ["github_actions_workflow_dispatch"],
        "emitted_event_names": [],
        "guardrails": [
            "project_auth_required",
            "api_token_actor_bound",
            "handler_managed_idempotency",
            "single_post_no_replay",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
    {
        "function_id": "github_actions.workflow.find_run",
        "handler": handle_workflow_find_run,
        "request_model": WorkflowFindRunRequest,
        "response_model": WorkflowFindRunResponse,
        "stability": "stable",
        "owner_module": __name__,
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
    {
        "function_id": "github_actions.run.jobs_count",
        "handler": handle_run_jobs_count,
        "request_model": RunJobsCountRequest,
        "response_model": RunJobsCountResponse,
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
    "REGISTRATIONS",
    "RunJobsCountRequest",
    "RunJobsCountResponse",
    "WorkflowDispatchRequest",
    "WorkflowDispatchOnceRequest",
    "WorkflowDispatchResponse",
    "WorkflowFindRunRequest",
    "WorkflowFindRunResponse",
    "handle_run_jobs_count",
    "handle_workflow_dispatch",
    "handle_workflow_dispatch_once",
    "handle_workflow_find_run",
]
