"""Handler for ``github_actions.wait_run``.

Point-in-time GitHub Actions workflow-run read used by the
``yoke github-actions wait-run`` client loop. The handler returns
immediately; timeout and sleep semantics
belong in the CLI adapter so HTTPS callers never hold one server
request open for a long polling window.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve,
)
from yoke_core.domain.ci_job_outcome import (
    CI_JOB_NOT_STARTED,
    REDISPATCH_RECOVERY,
    with_effective_conclusion,
)
from yoke_core.domain.github_actions_identifiers import WorkflowRunId
from yoke_core.domain.github_actions_run_stall import (
    CI_RUN_NEVER_STARTED_REASON,
    pending_run_message,
    run_concurrency_groups,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class RunGetRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    run_id: WorkflowRunId = Field(..., description="GitHub Actions run id.")
    project: str = Field(
        ...,
        min_length=1,
        description="Project capability owning the GitHub App repo binding.",
    )


class RunGetResponse(BaseModel):
    state: str
    run_id: str
    status: Optional[str] = None
    #: GitHub's conclusion, or ``ci_job_not_started`` for a completed run
    #: whose jobs never started (:mod:`yoke_core.domain.ci_job_outcome`).
    conclusion: Optional[str] = None
    html_url: Optional[str] = None
    #: The commit the run checked out. A caller that dispatched against a
    #: branch needs this to prove the conclusion belongs to the tree it
    #: meant to test, and it can only be read where the App credentials
    #: live.
    head_sha: Optional[str] = None
    updated_at: Optional[str] = None
    jobs_count: Optional[int] = Field(None, ge=0)
    message: str


def _classify(
    payload: RunGetRequest,
    data: Dict[str, Any],
    *,
    jobs_count: Optional[int] = None,
    concurrency_groups: Optional[tuple[str, ...]] = None,
) -> RunGetResponse:
    status = str(data.get("status") or "").strip()
    conclusion = str(data.get("conclusion") or "").strip() or None
    html_url = str(data.get("html_url") or "").strip() or None
    run_id = str(data.get("id") or payload.run_id)

    if status == "completed":
        if conclusion == "success":
            state, message = "success", "success"
        else:
            failure = conclusion or "unknown"
            state, message = "failed", f"failed:{failure}"
            if failure == CI_JOB_NOT_STARTED:
                message = f"{message} — {REDISPATCH_RECOVERY}"
    elif status in {"queued", "pending", "waiting"}:
        state, message = "waiting", "waiting"
        if status == "pending" and jobs_count is not None:
            message = pending_run_message(
                repo=payload.repo,
                run_id=run_id,
                jobs_count=jobs_count,
                updated_at=str(data.get("updated_at") or ""),
                concurrency_groups=concurrency_groups,
            )
            if CI_RUN_NEVER_STARTED_REASON in message:
                state = "failed"
    elif status == "in_progress":
        state, message = "running", "in_progress"
    else:
        state, message = "failed", f"unknown:{status}"

    return RunGetResponse(
        state=state,
        run_id=run_id,
        status=status or None,
        conclusion=conclusion,
        html_url=html_url,
        head_sha=str(data.get("head_sha") or "").strip() or None,
        updated_at=str(data.get("updated_at") or "").strip() or None,
        jobs_count=jobs_count,
        message=message,
    )


def _jobs_count(data: Any) -> Optional[int]:
    if not isinstance(data, dict) or "total_count" not in data:
        return None
    raw = data.get("total_count")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


def handle_run_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, err = _validate_and_resolve(
        request,
        RunGetRequest,
        "github_actions.wait_run",
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    if err is not None:
        return err

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    try:
        data = rest_get(
            f"/repos/{payload.repo}/actions/runs/{payload.run_id}",
            token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"run get failed: {exc}")
    if not isinstance(data, dict):
        return _transport_failed(f"run {payload.run_id} was not found")
    data = with_effective_conclusion(payload.repo, data, token=token) or data

    jobs_count = None
    concurrency_groups = None
    if str(data.get("status") or "").strip() == "pending":
        attempt = data.get("run_attempt") or 1
        try:
            jobs = rest_get(
                f"/repos/{payload.repo}/actions/runs/{payload.run_id}/"
                f"attempts/{attempt}/jobs",
                token=token,
            )
        except RestTransportError as exc:
            return _transport_failed(f"pending run jobs lookup failed: {exc}")
        jobs_count = _jobs_count(jobs)
        if jobs_count is None:
            return _transport_failed(
                "pending workflow jobs response omitted a valid total_count"
            )
        candidate = pending_run_message(
            repo=payload.repo,
            run_id=str(payload.run_id),
            jobs_count=jobs_count,
            updated_at=str(data.get("updated_at") or ""),
            concurrency_groups=(),
        )
        if CI_RUN_NEVER_STARTED_REASON in candidate:
            try:
                groups = rest_get(
                    f"/repos/{payload.repo}/actions/runs/{payload.run_id}/"
                    "concurrency_groups",
                    query={"per_page": "100"},
                    token=token,
                )
                concurrency_groups = run_concurrency_groups(groups)
            except (RestTransportError, ValueError) as exc:
                return _transport_failed(
                    f"pending run concurrency lookup failed: {exc}; "
                    "restore Actions read access and retry the wait; "
                    "missing queue evidence is not a stalled dispatch"
                )

    return HandlerOutcome(
        result_payload=_classify(
            payload,
            data,
            jobs_count=jobs_count,
            concurrency_groups=concurrency_groups,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github_actions.wait_run",
        "handler": handle_run_get,
        "request_model": RunGetRequest,
        "response_model": RunGetResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_actions_run",
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
    "RunGetRequest",
    "RunGetResponse",
    "handle_run_get",
]
