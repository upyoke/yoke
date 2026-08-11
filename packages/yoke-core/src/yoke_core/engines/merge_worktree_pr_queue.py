"""Merge-queue entry and membership reads for an item's pull request.

Queue entry is GitHub's merge-when-ready: ``enablePullRequestAutoMerge``
over GraphQL, carried on the same project-auth REST transport the other
PR helpers use (``POST /graphql`` is one more :class:`RestRequest`).
With a queue ruleset on the base branch, the mutation enqueues the PR
and the queue runs the CI workflow's ``merge_group`` gate on the train's
combined head; without a queue, GitHub refuses and the caller surfaces
the named reason instead of silently merging another way.

Membership reads power train-composition admission: queue entries map
back to items by head branch name, which the merge boundary names after
the item ref. The train run read answers what the queue's own
``merge_group`` gate concluded about the combined head, so a landing can
record it as covering evidence and name it in a refusal instead of
asserting a verdict it never read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

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
from yoke_core.engines.merge_worktree_pr_rest import (
    AuthResolutionFailed,
    resolve_auth,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


_ENABLE_AUTO_MERGE_MUTATION = """
mutation($pullRequestId: ID!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $pullRequestId}) {
    pullRequest { number autoMergeRequest { enabledAt } }
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
    """One queued PR, mapped back to its item by head branch name.

    ``state`` is the queue's own word for what the entry is doing —
    ``AWAITING_CHECKS`` while the train validates, ``MERGEABLE`` once it
    passes — and is the fact that distinguishes a PR the queue is still
    driving from one it has dropped.
    """

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
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """POST one GraphQL document; return ``(data, error_detail)``."""
    try:
        response = request_with_retry(
            RestRequest(
                method="POST",
                path="/graphql",
                body={"query": query, "variables": variables},
                replay_safe=True,
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return None, f"github graphql transport failure: {exc}"
    body = response.body if isinstance(response.body, dict) else {}
    errors = body.get("errors") or []
    if errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        message = str(first.get("message") or errors[0])
        return None, f"github graphql refused: {message}"
    data = body.get("data")
    return (data if isinstance(data, dict) else {}), None


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


def enter_merge_queue(ctx: MergeContext, pr_num: str) -> QueueEntryResult:
    """Enqueue ``pr_num`` with merge-when-ready.

    A refusal (no queue ruleset, auto-merge disallowed, PR not open) comes
    back as ``success=False`` with the named reason; callers must surface
    it rather than falling back to a direct merge.
    """
    auth, auth_err = resolve_auth_detail(ctx, PR_WRITE)
    if auth_err or auth is None:
        return QueueEntryResult(
            success=False, pr_num=pr_num, error_detail=auth_err
        )
    node_id, node_err = _pr_node_id(auth, pr_num)
    if node_err:
        return QueueEntryResult(
            success=False, pr_num=pr_num, error_detail=node_err
        )
    _, mutation_err = graphql_with_auth(
        auth,
        query=_ENABLE_AUTO_MERGE_MUTATION,
        variables={"pullRequestId": node_id},
    )
    if mutation_err:
        return QueueEntryResult(
            success=False, pr_num=pr_num, error_detail=mutation_err
        )
    return QueueEntryResult(success=True, pr_num=pr_num)


@dataclass(frozen=True)
class PrLandingState:
    """Merged/closed facts for one PR, read for queue-outcome polling."""

    merged: bool
    closed: bool
    auto_merge_active: bool


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
    return (
        PrLandingState(
            merged=bool(body.get("merged")),
            closed=str(body.get("state") or "") == "closed",
            auto_merge_active=body.get("auto_merge") is not None,
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
        members.append(QueueMember(
            pr_num=str(number),
            head_ref=head,
            state=str((node or {}).get("state") or ""),
        ))
    return members, None


@dataclass(frozen=True)
class TrainRun:
    """The ``merge_group`` workflow run validating one train's combined head."""

    status: str = ""
    conclusion: str = ""
    head_sha: str = ""
    url: str = ""
    matched_by_marker: bool = False


def read_train_run(
    ctx: MergeContext, pr_num: str
) -> tuple[Optional[TrainRun], Optional[str]]:
    """The merge_group run covering ``pr_num``'s train.

    Matched by the queue ref's ``pr-<number>-`` marker. A train that has
    already rotated out of the recent-run window falls back to the newest
    successful merge_group run, reported as ``matched_by_marker=False`` so a
    caller can say the identity was inferred. Returns ``(None, reason)`` when
    the run cannot be read at all; no caller blocks on that.
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
    body = response.body if isinstance(response.body, dict) else {}
    marker = f"pr-{pr_num}-"
    matched: Optional[dict[str, Any]] = None
    newest_success: Optional[dict[str, Any]] = None
    for run in body.get("workflow_runs") or []:
        if not isinstance(run, dict):
            continue
        head_branch = str(run.get("head_branch") or "")
        if not head_branch.startswith(_QUEUE_REF_PREFIX):
            continue
        if marker in head_branch:
            matched = run
            break
        if newest_success is None and run.get("conclusion") == "success":
            newest_success = run
    chosen = matched or newest_success
    if chosen is None:
        return None, "no merge_group workflow run found for the landed train"
    return (
        TrainRun(
            status=str(chosen.get("status") or ""),
            conclusion=str(chosen.get("conclusion") or ""),
            head_sha=str(chosen.get("head_sha") or ""),
            url=str(chosen.get("html_url") or ""),
            matched_by_marker=matched is not None,
        ),
        None if matched is not None else (
            "merge_group run matched by recency, not by queue ref marker"
        ),
    )


__all__ = [
    "PrLandingState",
    "QueueEntryResult",
    "QueueMember",
    "TrainRun",
    "enter_merge_queue",
    "graphql_with_auth",
    "read_pr_landing_state",
    "read_queue_members",
    "read_train_run",
]
