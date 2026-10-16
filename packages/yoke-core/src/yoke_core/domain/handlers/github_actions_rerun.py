"""Recover CI only on an item's current, newest landing-PR run."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import item_field_transform
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_actions_identifiers import (
    WorkflowRunId,
    repository_api_path,
)
from yoke_core.domain.github_actions_rest import rest_get, rest_post
from yoke_core.domain.github_actions_rerun_safety import checked_run
from yoke_core.domain.handlers.github_actions_set import _auth_failed
from yoke_core.domain.item_detail_read import get_item_detail
from yoke_core.domain.progress_log import PROGRESS_LOG_ORDERING, PROGRESS_LOG_SECTION
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message

FUNCTION_ID = "github_actions.run.rerun_failed"


class RerunFailedRequest(BaseModel):
    run_id: WorkflowRunId


class RerunFailedResponse(BaseModel):
    run_id: str
    head_sha: str
    pr_number: str
    accepted: bool
    html_url: str


def _refused(code: str, message: str, **facts) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        result_payload=facts,
        error=FunctionError(code=code, message=message),
    )


def _record(item_id: int, content: str) -> bool:
    result = item_field_transform.section_append(
        item_id=item_id,
        section=PROGRESS_LOG_SECTION,
        headline="CI rerun",
        content=content,
        ordering=PROGRESS_LOG_ORDERING,
        source=FUNCTION_ID,
    )
    return result.success


def handle_rerun_failed(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return _refused(
            "target_invalid",
            "Select the claimed work item with its recorded landing PR.",
        )
    try:
        payload = RerunFailedRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _refused("invalid_payload", safe_validation_message(exc))
    item_id = int(request.target.item_id)
    try:
        item = get_item_detail(item_id)
    except LookupError as exc:
        return _refused("not_found", f"{exc}; select an existing claimed item.")
    project = str((item.get("project") or {}).get("slug") or "")
    pr_number = str((item.get("merge_queue") or {}).get("pr_number") or "")
    if not pr_number.isdigit() or int(pr_number) < 1:
        return _refused(
            "ci_rerun_pr_missing",
            "Item has no recorded landing PR; run its merge/QA boundary to publish and record the PR first.",
        )
    try:
        auth = resolve_project_github_auth(
            project,
            required_permissions={
                **GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
                **GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
            },
        )
    except ProjectGithubAuthError as exc:
        return _auth_failed(exc, project)
    root = repository_api_path(auth.repo)
    try:
        run = checked_run(root, pr_number, payload.run_id, auth.token, get=rest_get)
    except RestTransportError as exc:
        return _refused(
            "ci_rerun_read_failed",
            f"Safety reads failed: {exc}; restore GitHub access and retry. No rerun was sent.",
        )
    if isinstance(run, HandlerOutcome):
        return run
    facts = RerunFailedResponse(
        run_id=payload.run_id,
        head_sha=run["head_sha"],
        pr_number=pr_number,
        accepted=False,
        html_url=str(run.get("html_url") or ""),
    ).model_dump()
    identity = f"{auth.repo} PR {pr_number}, run {payload.run_id}, head {run['head_sha']}, attempt {run.get('run_attempt')}; {facts['html_url']}"
    if not _record(
        item_id,
        f"Rerun intent: {identity}. Safety checks passed; one POST will be attempted.",
    ):
        return _refused(
            "ci_rerun_record_failed",
            "Could not persist rerun intent in the item's Progress Log; restore item writes and retry. No rerun was sent.",
            **facts,
        )
    # Persisting the intent can take time; refresh identity immediately before POST.
    try:
        refreshed = checked_run(
            root, pr_number, payload.run_id, auth.token, get=rest_get
        )
    except RestTransportError as exc:
        refreshed = _refused(
            "ci_rerun_read_failed",
            f"Final safety read failed: {exc}; restore GitHub access and retry. No rerun was sent.",
        )
    if isinstance(refreshed, HandlerOutcome):
        recorded = _record(
            item_id,
            f"Rerun refused after intent: {identity}. {refreshed.error.code}: {refreshed.error.message}",
        )
        if not recorded:
            refreshed.error.message += " Refusal recording also failed; restore item writes and append this receipt."
        return refreshed
    if (
        refreshed["head_sha"],
        refreshed.get("run_attempt"),
        refreshed["rerun_endpoint"],
    ) != (run["head_sha"], run.get("run_attempt"), run["rerun_endpoint"]):
        _record(
            item_id,
            f"Rerun refused after intent: {identity}. ci_rerun_attempt_changed; inspect the current attempt.",
        )
        return _refused(
            "ci_rerun_attempt_changed",
            "Run changed during intent recording; inspect its current attempt before retrying. No rerun was sent.",
            **facts,
        )
    try:
        rest_post(
            f"{root}/actions/runs/{payload.run_id}/{refreshed['rerun_endpoint']}",
            body={},
            token=auth.token,
            max_attempts=1,
        )
    except RestTransportError as exc:
        definitive = exc.status is not None and 400 <= exc.status < 500
        code = "ci_rerun_rejected" if definitive else "ci_rerun_ambiguous"
        recovery = "Inspect the run's attempt/status before any retry; the POST was not retried."
        recorded = _record(item_id, f"{code}: {identity}. {exc}. {recovery}")
        suffix = (
            ""
            if recorded
            else " Outcome recording also failed; restore item writes and append this receipt to the Progress Log."
        )
        return _refused(code, f"{exc}. {recovery}{suffix}", **facts)
    facts["accepted"] = True
    if not _record(
        item_id,
        f"GitHub accepted CI rerun: {identity}. Resume the same CI/QA wait for its new attempt.",
    ):
        return _refused(
            "ci_rerun_record_failed",
            "GitHub accepted the rerun, but outcome recording failed; restore item writes and append this receipt to the Progress Log. Resume the CI wait; do not rerun again.",
            **facts,
        )
    return HandlerOutcome(primary_success=True, result_payload=facts)


REGISTRATIONS = [
    {
        "function_id": FUNCTION_ID,
        "handler": handle_rerun_failed,
        "request_model": RerunFailedRequest,
        "response_model": RerunFailedResponse,
        "stability": "stable",
        "owner_module": __name__,
        "target_kinds": ["item"],
        "side_effects": ["github:rerun_failed_jobs", "item_progress_log_append"],
        "emitted_event_names": [],
        "guardrails": [
            "current_pr_head",
            "newest_workflow_run",
            "project_auth_required",
        ],
        "adapter_status": "live",
        "claim_required_kind": "item",
        "minimum_serving_version": "next-release",
    }
]
