"""Handler for ``github_actions.failed_log`` — every failed job of a run."""

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
from yoke_core.domain.github_actions_failed_job_report import build_failed_job_report
from yoke_core.domain.github_actions_failure_region import DEFAULT_REGION_LINES


class FailedLogRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    project: str = Field(..., min_length=1)
    run_id: Optional[WorkflowRunId] = None
    workflow: Optional[WorkflowIdentifier] = None
    branch: str = Field("main")
    head_sha: str = Field("")
    # Applied per failed job, so one shard's region never displaces another's.
    max_lines: int = Field(DEFAULT_REGION_LINES, ge=1)
    # Also return each failed job's signed complete-log download address,
    # so the caller writes the whole log locally instead of receiving it
    # through this bounded response.
    full: bool = False

    @model_validator(mode="after")
    def _requires_run_selector(self) -> "FailedLogRequest":
        if not str(self.run_id or "").strip() and not str(self.workflow or "").strip():
            raise ValueError("run_id or workflow is required")
        return self


class FailedJobSummary(BaseModel):
    job_id: str
    name: str
    conclusion: str
    html_url: str
    log_status: str
    log_detail: str
    log_line_count: int
    region: str
    region_line_count: int
    trimmed_line_count: int
    log_download_url: str = ""
    log_download_detail: str = ""


class FailedLogResponse(BaseModel):
    run_id: str
    output: str
    truncated: bool = False
    failed_job_count: int = 0
    logs_available_count: int = 0
    unfinished_job_count: int = 0
    jobs: List[FailedJobSummary] = Field(default_factory=list)


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
    from yoke_core.domain.github_actions_failed_jobs import (
        collect_failed_jobs,
        resolve_log_downloads,
    )

    try:
        failures = collect_failed_jobs(payload.repo, run_id, token=token)
    except RestAuthError as exc:
        return _transport_failed(
            f"GitHub auth failure fetching logs for run {run_id}: {exc}",
        )
    except RestTransportError as exc:
        return _transport_failed(f"failed to fetch logs for run {run_id}: {exc}")

    # Resolved last: GitHub's signed addresses live about one minute.
    downloads = (
        resolve_log_downloads(payload.repo, failures.failed, token=token)
        if payload.full
        else None
    )
    report = build_failed_job_report(
        failures,
        repo=payload.repo,
        run_id=run_id,
        max_lines=payload.max_lines,
        downloads=downloads,
    )
    return HandlerOutcome(
        result_payload=FailedLogResponse(
            run_id=run_id,
            output=report.output,
            truncated=report.truncated,
            failed_job_count=report.failed_job_count,
            logs_available_count=report.logs_available_count,
            unfinished_job_count=report.unfinished_job_count,
            jobs=[FailedJobSummary(**job) for job in report.jobs],
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
    "FailedJobSummary",
    "FailedLogRequest",
    "FailedLogResponse",
    "REGISTRATIONS",
    "handle_failed_log",
]
