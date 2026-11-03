"""List every Actions run for one exact commit, from the control plane.

A watcher waiting on CI runs on the caller's machine, where GitHub App
private keys deliberately never live, so the read it needs has to happen
where the project's installation authority is. The matching rules travel with
it rather than being restated at the call site: runs are selected by the
``head_sha`` query, re-checked against each returned ``head_sha``, and
narrowed by the workflow's own name rather than a run's display title.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve_auth,
)


OWNER_MODULE = "yoke_core.domain.handlers.github_actions_commit_runs"
FUNCTION_ID = "github_actions.commit_runs.list"


class CommitRunsListRequest(BaseModel):
    project: str = Field(..., min_length=1)
    head_sha: str = Field(..., min_length=7)
    # The project's bound repository is the answer whenever the caller does
    # not name one, because a caller with no local App authority cannot read
    # the binding either — which is the whole reason this read is relayed.
    repo: Optional[str] = None
    workflow: str = ""


class CommitRun(BaseModel):
    id: str
    name: str = ""
    status: str = ""
    conclusion: str = ""
    html_url: str = ""
    head_sha: str = ""
    head_branch: str = ""
    event: str = ""


class CommitRunsListResponse(BaseModel):
    repo: str
    head_sha: str
    runs: List[CommitRun] = Field(default_factory=list)


def _selected(
    data: Any,
    head_sha: str,
    workflow_id: str,
) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        return []
    selected: List[Dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if str(run.get("head_sha") or "") != head_sha:
            continue
        if workflow_id and str(run.get("workflow_id") or "") != workflow_id:
            continue
        selected.append(run)
    return selected


def _workflows(repo: str, *, token: str) -> List[Dict[str, Any]]:
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    workflows: List[Dict[str, Any]] = []
    page = 1
    while True:
        data = rest_get(
            f"/repos/{repo}/actions/workflows",
            query={"per_page": "100", "page": str(page)},
            token=token,
        )
        entries = data.get("workflows") if isinstance(data, dict) else None
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or not entry.get("id") for entry in entries
        ):
            raise RestTransportError("GitHub workflows response is malformed")
        workflows.extend(entries)
        if len(entries) < 100:
            return workflows
        page += 1


def handle_commit_runs_list(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the runs for exactly one commit in the project's repository."""
    payload, resolved, error = _validate_and_resolve_auth(
        request,
        CommitRunsListRequest,
        FUNCTION_ID,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    if error is not None:
        return error
    assert payload is not None and resolved is not None

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    repo = str(payload.repo or resolved.repo or "").strip()
    if not repo:
        return _transport_failed(
            "the project's GitHub binding names no repository to read runs from"
        )
    head_sha = payload.head_sha.strip()
    workflow_id = ""
    try:
        if payload.workflow:
            workflows = _workflows(repo, token=resolved.token)
            matches = [
                workflow
                for workflow in workflows
                if payload.workflow
                in (
                    workflow.get("name"),
                    workflow.get("path"),
                    str(workflow.get("path") or "").rsplit("/", 1)[-1],
                )
            ]
            if len(matches) != 1:
                code = "workflow_not_found" if not matches else "workflow_ambiguous"
                names = (
                    ", ".join(
                        f"{workflow.get('name')} ({workflow.get('path')})"
                        for workflow in workflows
                    )
                    or "(none)"
                )
                return HandlerOutcome(
                    result_payload={},
                    primary_success=False,
                    error=FunctionError(
                        code=code,
                        message=compose_refusal(
                            f"{code}: {payload.workflow!r} does not identify one workflow in {repo}",
                            evaluated=f"repository workflows: {names}",
                            recovery="Retry --workflow with a listed workflow name or file path",
                        ),
                    ),
                )
            workflow_id = str(matches[0]["id"])
        data = rest_get(
            f"/repos/{repo}/actions/runs",
            query={"head_sha": head_sha, "per_page": "100"},
            token=resolved.token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"commit run lookup failed: {exc}")

    runs = [
        CommitRun(
            id=str(run.get("id") or ""),
            name=str(run.get("name") or ""),
            status=str(run.get("status") or ""),
            conclusion=str(run.get("conclusion") or ""),
            html_url=str(run.get("html_url") or ""),
            head_sha=str(run.get("head_sha") or ""),
            head_branch=str(run.get("head_branch") or ""),
            event=str(run.get("event") or ""),
        )
        for run in _selected(data, head_sha, workflow_id)
    ]
    return HandlerOutcome(
        result_payload=CommitRunsListResponse(
            repo=repo, head_sha=head_sha, runs=runs
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS = [
    {
        "function_id": FUNCTION_ID,
        "handler": handle_commit_runs_list,
        "request_model": CommitRunsListRequest,
        "response_model": CommitRunsListResponse,
        "stability": "stable",
        "owner_module": OWNER_MODULE,
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
]


__all__ = [
    "FUNCTION_ID",
    "REGISTRATIONS",
    "CommitRun",
    "CommitRunsListRequest",
    "CommitRunsListResponse",
    "handle_commit_runs_list",
]
