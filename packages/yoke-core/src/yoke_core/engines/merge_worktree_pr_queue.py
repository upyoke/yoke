"""Merge-queue entry, membership, and landing-state reads for an item PR.

Queue entry is GitHub's merge-when-ready over GraphQL.
``leave_merge_queue`` disarms it so a red entry ticket cannot auto-merge
later. Membership reads power train admission; the train run read names
the ``merge_group`` gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS as ACTIONS_READ,
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
    GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS as PR_WRITE,
)

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.domain.project_ci_workflow import project_ci_workflow_file
from yoke_core.engines.merge_worktree_pr_rest import (
    AuthResolutionFailed,
    resolve_auth,
)
from yoke_core.engines.merge_worktree_pr_graphql import (
    graphql_with_auth as _graphql_with_auth,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


_ENABLE_AUTO_MERGE_MUTATION = """
mutation($pullRequestId: ID!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $pullRequestId}) {
    pullRequest { number autoMergeRequest { enabledAt } }
  }
}
"""

_DISABLE_AUTO_MERGE_MUTATION = """
mutation($pullRequestId: ID!) {
  disablePullRequestAutoMerge(input: {pullRequestId: $pullRequestId}) {
    pullRequest { number }
  }
}
"""

_MERGE_QUEUE_ENTRIES_QUERY = """
query($owner: String!, $name: String!, $branch: String!) {
  repository(owner: $owner, name: $name) {
    mergeQueue(branch: $branch) {
      entries(first: 50) {
        nodes {
          state
          pullRequest { number headRefName }
        }
      }
    }
  }
}
"""

# Every branch the queue builds a train on is named under this prefix, and
# each carries a ``pr-<number>-`` marker naming its members.
_QUEUE_REF_PREFIX = "gh-readonly-queue/"


@dataclass(frozen=True)
class QueueEntryResult:
    """Outcome of enqueueing one PR via merge-when-ready."""

    success: bool
    pr_num: str = ""
    error_detail: Optional[str] = None


@dataclass(frozen=True)
class QueueMember:
    """One queued PR, mapped back to its item by head branch name."""

    pr_num: str
    head_ref: str
    state: str = ""


def resolve_auth_detail(
    ctx: MergeContext, required_permissions: Any
) -> tuple[Optional[ProjectGithubAuth], Optional[str]]:
    try:
        return resolve_auth(ctx, required_permissions=required_permissions), None
    except AuthResolutionFailed as exc:
        detail = str(exc)
        if exc.hint:
            detail = f"{detail} (repair: {exc.hint})"
        return None, detail


def graphql_with_auth(
    auth: ProjectGithubAuth,
    *,
    query: str,
    variables: dict[str, Any],
    required_permissions: Mapping[str, str],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """POST one GraphQL document; return ``(data, error_detail)``."""
    return _graphql_with_auth(
        auth,
        query=query,
        variables=variables,
        required_permissions=required_permissions,
        request=request_with_retry,
    )


def _pr_node_id(
    auth: ProjectGithubAuth, pr_num: str
) -> tuple[Optional[str], Optional[str]]:
    """Resolve the PR's GraphQL node id through the REST read."""
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/pulls/{pr_num}",
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return None, f"github pr read failure: {exc}"
    body = response.body if isinstance(response.body, dict) else {}
    node_id = str(body.get("node_id") or "")
    if not node_id:
        return None, f"pull request {pr_num} returned no node id"
    return node_id, None


def _mutate_auto_merge(
    ctx: MergeContext, pr_num: str, mutation: str
) -> QueueEntryResult:
    """Enable or disable merge-when-ready; refusals stay named."""
    auth, auth_err = resolve_auth_detail(ctx, PR_WRITE)
    if auth_err or auth is None:
        return QueueEntryResult(success=False, pr_num=pr_num, error_detail=auth_err)
    node_id, node_err = _pr_node_id(auth, pr_num)
    if node_err:
        return QueueEntryResult(success=False, pr_num=pr_num, error_detail=node_err)
    _, mutation_err = graphql_with_auth(
        auth,
        query=mutation,
        variables={"pullRequestId": node_id},
        required_permissions=PR_WRITE,
    )
    if mutation_err:
        return QueueEntryResult(success=False, pr_num=pr_num, error_detail=mutation_err)
    return QueueEntryResult(success=True, pr_num=pr_num)


def enter_merge_queue(ctx: MergeContext, pr_num: str) -> QueueEntryResult:
    """Enqueue ``pr_num`` with merge-when-ready; refusals stay named."""
    return _mutate_auto_merge(ctx, pr_num, _ENABLE_AUTO_MERGE_MUTATION)


def leave_merge_queue(ctx: MergeContext, pr_num: str) -> QueueEntryResult:
    """Disarm merge-when-ready so a later green cannot auto-merge."""
    return _mutate_auto_merge(ctx, pr_num, _DISABLE_AUTO_MERGE_MUTATION)


@dataclass(frozen=True)
class PrLandingState:
    """Merged/closed facts for one PR, read for queue-outcome polling."""

    merged: bool
    closed: bool
    auto_merge_active: bool
    merge_state_status: str = ""
    head_sha: str = ""


def read_pr_landing_state(
    ctx: MergeContext, pr_num: str
) -> tuple[Optional[PrLandingState], Optional[str]]:
    """Read whether ``pr_num`` merged, closed, or left the queue."""
    auth, auth_err = resolve_auth_detail(ctx, PR_READ)
    if auth_err or auth is None:
        return None, auth_err
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/pulls/{pr_num}",
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return None, f"github pr read failure: {exc}"
    body = response.body if isinstance(response.body, dict) else {}
    head = body.get("head")
    head_sha = str(head.get("sha") or "").strip() if isinstance(head, dict) else ""
    return (
        PrLandingState(
            merged=bool(body.get("merged")),
            closed=str(body.get("state") or "") == "closed",
            auto_merge_active=body.get("auto_merge") is not None,
            merge_state_status=str(body.get("mergeable_state") or "").lower(),
            head_sha=head_sha,
        ),
        None,
    )


def read_queue_members(
    ctx: MergeContext, *, base_branch: str = "main"
) -> tuple[Optional[list[QueueMember]], Optional[str]]:
    """List current queue entries for the base branch.

    Returns ``(members, None)`` on success — an empty list when the queue
    is empty — or ``(None, error_detail)`` when the repository has no
    queue or the read fails; callers treat that as a named refusal, not
    an empty queue.
    """
    auth, auth_err = resolve_auth_detail(ctx, PR_READ)
    if auth_err or auth is None:
        return None, auth_err
    owner, name = split_repo(auth.repo)
    data, err = graphql_with_auth(
        auth,
        query=_MERGE_QUEUE_ENTRIES_QUERY,
        variables={"owner": owner, "name": name, "branch": base_branch},
        required_permissions=PR_READ,
    )
    if err:
        return None, err
    repo = f"{owner}/{name}"
    queue = ((data or {}).get("repository") or {}).get("mergeQueue")
    if not isinstance(queue, dict):
        return None, (
            f"repository {repo} reports no merge queue on {base_branch!r}; "
            "configure the queue ruleset before selecting the queue route"
        )
    nodes = ((queue.get("entries") or {}).get("nodes")) or []
    members: list[QueueMember] = []
    for node in nodes:
        pr = (node or {}).get("pullRequest") or {}
        number = pr.get("number")
        head = str(pr.get("headRefName") or "")
        if number is None or not head:
            continue
        members.append(
            QueueMember(
                pr_num=str(number),
                head_ref=head,
                state=str((node or {}).get("state") or ""),
            )
        )
    return members, None


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


__all__ = [
    "PrLandingState",
    "QueueEntryResult",
    "QueueMember",
    "TrainRun",
    "enter_merge_queue",
    "graphql_with_auth",
    "leave_merge_queue",
    "read_pr_landing_state",
    "read_queue_members",
    "read_train_run",
]
