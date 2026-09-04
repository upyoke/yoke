"""Cancel the older pull-request run replaced by a rebased QA gate.

The QA runner executes this operation from the machine that opened the pull
request. Keeping the REST call on that machine means a gate can use the fix
before a newly added control-plane handler has itself been deployed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import (
    github_actions_rest,
    project_github_auth,
    qa_case_ci_progress,
)
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


_ACTIVE_RUN_STATUSES = frozenset(
    {"requested", "queued", "pending", "waiting", "in_progress"}
)


def _superseded_run(
    data: Any,
    *,
    branch: str,
    current_head_sha: str,
) -> Optional[Dict[str, Any]]:
    """Return the newest older run on the exact pull-request branch."""
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise QaCaseExecutionError(
            "superseded workflow-run lookup omitted workflow_runs"
        )
    for run in data["workflow_runs"]:
        if not isinstance(run, dict):
            raise QaCaseExecutionError(
                "superseded workflow-run lookup returned a malformed run"
            )
        if str(run.get("head_branch") or "") != branch:
            continue
        head_sha = str(run.get("head_sha") or "")
        if head_sha and head_sha != current_head_sha:
            return run
    return None


def _machine_token(*, project: str, repo: str) -> str:
    """Resolve Actions-write auth from the machine's bound user authority."""
    from yoke_cli.commands.merge_item_local_runtime import (
        LocalMergeGithubAuthorityError,
        machine_github_user_authority,
    )

    try:
        with machine_github_user_authority():
            resolved = project_github_auth.resolve_project_github_auth(
                project,
                required_permissions=GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
            )
    except (
        LocalMergeGithubAuthorityError,
        project_github_auth.ProjectGithubAuthError,
    ) as exc:
        raise QaCaseExecutionError(
            f"could not resolve GitHub authority for superseded-run cancellation: {exc}"
        ) from exc
    if resolved.repo.casefold() != repo.casefold():
        raise QaCaseExecutionError(
            "could not cancel a superseded run: requested repository "
            f"{repo!r} does not match project {project!r} binding "
            f"{resolved.repo!r}"
        )
    return resolved.token


def _race_concluded(*, repo: str, run_id: str, token: str) -> bool:
    try:
        refreshed = github_actions_rest.rest_get(
            f"/repos/{repo}/actions/runs/{run_id}", token=token
        )
    except RestTransportError:
        return False
    return (
        isinstance(refreshed, dict)
        and str(refreshed.get("status") or "") == "completed"
    )


def _force_cancel_run(*, repo: str, run_id: str, token: str) -> bool:
    """Cancel one active run; a run that concluded in the race is settled."""
    try:
        github_actions_rest.rest_post(
            f"/repos/{repo}/actions/runs/{run_id}/force-cancel",
            body={},
            token=token,
            max_attempts=1,
        )
    except RestTransportError as exc:
        if exc.status in {409, 422} and _race_concluded(
            repo=repo,
            run_id=run_id,
            token=token,
        ):
            return False
        raise QaCaseExecutionError(
            f"could not force-cancel workflow run {run_id}: {exc}"
        ) from exc
    return True


def force_cancel_run(*, project: str, repo: str, run_id: str) -> bool:
    """Force-cancel one CI run with the gate machine's GitHub authority."""
    return _force_cancel_run(
        repo=repo,
        run_id=run_id,
        token=_machine_token(project=project, repo=repo),
    )


def force_cancel_if_rebased(
    *,
    project: str,
    repo: str,
    workflow: str,
    branch: str,
    previous_head_sha: str,
    current_head_sha: str,
) -> str:
    """Force-cancel the prior active run when a rebase changed the lane head."""
    if not previous_head_sha or previous_head_sha == current_head_sha:
        return ""

    token = _machine_token(project=project, repo=repo)
    try:
        data = github_actions_rest.rest_get(
            f"/repos/{repo}/actions/workflows/{workflow}/runs",
            query={
                "branch": branch,
                "event": "pull_request",
                "per_page": "10",
            },
            token=token,
        )
        candidate = _superseded_run(
            data,
            branch=branch,
            current_head_sha=current_head_sha,
        )
    except RestTransportError as exc:
        raise QaCaseExecutionError(
            f"could not find the superseded pull-request run for {repo}@{branch}: {exc}"
        ) from exc
    if candidate is None:
        return ""

    run_id = str(candidate.get("id") or "").strip()
    if not run_id:
        raise QaCaseExecutionError("superseded workflow run omitted its run id")
    status = str(candidate.get("status") or "").strip()
    if status == "completed":
        return ""
    if status not in _ACTIVE_RUN_STATUSES:
        raise QaCaseExecutionError(
            f"superseded workflow run {run_id} has unknown status {status!r}; "
            "inspect the run and retry the gate"
        )

    if not _force_cancel_run(repo=repo, run_id=run_id, token=token):
        return ""

    qa_case_ci_progress.announce_superseded_run_cancelled(
        repo=repo,
        branch=branch,
        run_id=run_id,
    )
    return run_id


__all__ = ["force_cancel_if_rebased", "force_cancel_run"]
