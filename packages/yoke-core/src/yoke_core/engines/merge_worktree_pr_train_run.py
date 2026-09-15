"""The ``merge_group`` workflow run that validates one train's combined head.

Separate from :mod:`yoke_core.engines.merge_worktree_pr_queue`, which owns
the pull request's own queue entry and arming. This module answers a
different question — what GitHub Actions ran for the train the pull request
was folded into — and reads Actions rather than pull requests to answer it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS as ACTIONS_READ,
)

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.project_ci_workflow import project_ci_workflow_file
from yoke_core.engines.merge_worktree_pr_queue import resolve_auth_detail
from yoke_core.engines.merge_worktree_prepare import MergeContext


# Every branch the queue builds a train on is named under this prefix, and
# each carries a ``pr-<number>-`` marker naming its members.
_QUEUE_REF_PREFIX = "gh-readonly-queue/"


@dataclass(frozen=True)
class TrainRun:
    """The ``merge_group`` workflow run validating one train's combined head."""

    status: str = ""
    conclusion: str = ""
    head_sha: str = ""
    url: str = ""


def read_train_run(
    ctx: MergeContext, pr_num: str
) -> tuple[Optional[TrainRun], Optional[str]]:
    """The merge_group run covering ``pr_num``'s train.

    Identified by both the queue ref's ``pr-<number>-`` marker and the
    project's declared CI workflow. Returns ``(None, reason)`` rather than
    substituting another workflow or train.
    """
    auth, auth_err = resolve_auth_detail(ctx, ACTIONS_READ)
    if auth_err or auth is None:
        return None, f"merge_group run lookup unavailable: {auth_err}"
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/actions/runs",
                query={"event": "merge_group", "per_page": "30"},
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return None, f"merge_group run lookup failed: {exc}"
    try:
        workflow = project_ci_workflow_file(str(ctx.project or ""))
    except RuntimeError as exc:
        return None, f"merge_group workflow identity lookup failed: {exc}"
    if not workflow:
        return None, "merge_group workflow identity is not declared"
    workflow_path = f".github/workflows/{workflow}"
    body = response.body if isinstance(response.body, dict) else {}
    marker = f"pr-{pr_num}-"
    for run in body.get("workflow_runs") or []:
        if not isinstance(run, dict):
            continue
        if str(run.get("path") or "") != workflow_path:
            continue
        head_branch = str(run.get("head_branch") or "")
        if not head_branch.startswith(_QUEUE_REF_PREFIX):
            continue
        if marker in head_branch:
            return (
                TrainRun(
                    status=str(run.get("status") or ""),
                    conclusion=str(run.get("conclusion") or ""),
                    head_sha=str(run.get("head_sha") or ""),
                    url=str(run.get("html_url") or ""),
                ),
                None,
            )
    return None, (
        f"no merge_group workflow run identified for pull request {pr_num}: "
        f"no recent {workflow!r} queue ref carries the marker {marker!r}"
    )


__all__ = ["TrainRun", "read_train_run"]
