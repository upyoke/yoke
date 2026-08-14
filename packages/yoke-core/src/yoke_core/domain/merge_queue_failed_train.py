"""Refuse queue re-entry that would replay a known failed train.

A train that already failed for this pull request's current head and the
current base will fail the same way. Re-entering burns another full suite
to reproduce a known verdict. A change to either input is a new train.
Uncertainty fails open: an unreadable train is not a known outcome.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_METADATA_READ_PERMISSION_LEVELS as METADATA_READ,
)
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    TrainRun,
    read_train_run,
    resolve_auth_detail,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext

FAILED_TRAIN_UNCHANGED = "failed-train-unchanged"


def _commit_parents(ctx: MergeContext, sha: str) -> list[str]:
    auth, error = resolve_auth_detail(ctx, METADATA_READ)
    if error or auth is None or not sha:
        return []
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/git/commits/{sha}",
            ),
            token=auth.token,
        )
    except RestTransportError:
        return []
    body = response.body if isinstance(response.body, dict) else {}
    parents = []
    for parent in body.get("parents") or []:
        if not isinstance(parent, dict):
            continue
        parent_sha = str(parent.get("sha") or "").strip()
        if parent_sha:
            parents.append(parent_sha)
    return parents


def _current_base_sha(ctx: MergeContext, base_branch: str) -> str:
    from yoke_core.domain import standalone_item_merge_git as git

    if not ctx.repo_root:
        return ""
    return (
        git.git_out(
            ctx.repo_root, "rev-parse", f"refs/remotes/origin/{base_branch}",
        )
        or git.head_of(ctx.repo_root, base_branch)
    )


def _base_covers_train(ctx: MergeContext, base_sha: str, train_sha: str) -> bool:
    from yoke_core.domain import standalone_item_merge_git as git

    if not ctx.repo_root or not base_sha or not train_sha:
        return False
    return git.is_ancestor(ctx.repo_root, base_sha, train_sha)


def _refusal(pr_num: str) -> str:
    return (
        f"{FAILED_TRAIN_UNCHANGED}: pull request {pr_num} already has a "
        "failed train for this head and base; change the branch head or "
        "wait for the base to move before re-entering the queue"
    )


def unchanged_failed_train_refusal(
    ctx: MergeContext,
    pr_num: str,
    *,
    lane_head: str,
    base_branch: str,
    train: Optional[TrainRun] = None,
    parents: Optional[list[str]] = None,
    base_sha: str = "",
) -> Optional[str]:
    """Named refusal, or ``None`` when re-entry is allowed."""
    observed = train
    if observed is None:
        observed, _note = read_train_run(ctx, pr_num)
    if observed is None or str(observed.conclusion or "") != "failure":
        return None
    train_sha = str(observed.head_sha or "").strip()
    if not train_sha:
        return None
    resolved = list(parents) if parents is not None else _commit_parents(
        ctx, train_sha,
    )
    if len(resolved) >= 2:
        trained_base, trained_head = resolved[0], resolved[1]
    elif resolved:
        trained_base, trained_head = "", resolved[0]
    else:
        trained_base, trained_head = "", train_sha
    head = (lane_head or "").strip()
    if not head or head != trained_head:
        return None
    current_base = (base_sha or _current_base_sha(ctx, base_branch)).strip()
    if trained_base:
        if current_base and current_base == trained_base:
            return _refusal(pr_num)
        return None
    if current_base and _base_covers_train(ctx, current_base, train_sha):
        return _refusal(pr_num)
    return None


__all__ = [
    "FAILED_TRAIN_UNCHANGED",
    "unchanged_failed_train_refusal",
]
