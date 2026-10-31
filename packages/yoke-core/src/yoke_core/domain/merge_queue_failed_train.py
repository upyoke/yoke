"""Refuse queue re-entry that would replay a known failed train.

A failed train needs a changed head or base before queue re-entry.
Uncertainty fails open: an unreadable train is not a known outcome.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS as CONTENTS_READ,
)
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.engines.merge_worktree_pr_queue import resolve_auth_detail
from yoke_core.engines.merge_worktree_pr_train_run import TrainRun, read_train_run
from yoke_core.engines.merge_worktree_prepare import MergeContext

FAILED_TRAIN_UNCHANGED = "failed-train-unchanged"


def _github_commit_read(ctx: MergeContext, resource: str) -> dict:
    """Serving observers have no checkout; read commit identity from GitHub."""
    auth, error = resolve_auth_detail(ctx, CONTENTS_READ)
    if error or auth is None:
        return {}
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(method="GET", path=f"/repos/{owner}/{repo}/{resource}"),
            token=auth.token,
        )
    except RestTransportError:
        return {}
    return response.body if isinstance(response.body, dict) else {}


def _commit_parents(ctx: MergeContext, sha: str) -> list[str]:
    if not sha:
        return []
    body = _github_commit_read(ctx, f"git/commits/{sha}")
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
        body = _github_commit_read(ctx, f"commits/{quote(base_branch, safe='')}")
        return str(body.get("sha") or "").strip()
    return git.git_out(
        ctx.repo_root,
        "rev-parse",
        f"refs/remotes/origin/{base_branch}",
    ) or git.head_of(ctx.repo_root, base_branch)


def _base_covers_train(ctx: MergeContext, base_sha: str, train_sha: str) -> bool:
    from yoke_core.domain import standalone_item_merge_git as git

    if not base_sha or not train_sha:
        return False
    if not ctx.repo_root:
        body = _github_commit_read(ctx, f"compare/{base_sha}...{train_sha}")
        return body.get("status") in {"ahead", "identical"}
    return git.is_ancestor(ctx.repo_root, base_sha, train_sha)


def _refusal(
    pr_num: str,
    train: TrainRun,
    *,
    lane_head: str,
    base_sha: str,
    trained_base: str,
) -> str:
    # Provider values stay on one output line, including control characters.
    # Keep the revision exactly as observed; never expand a shortened SHA.
    identity = f"combined head={train.head_sha.strip()!r}"
    if train.url.strip():
        identity += f", run URL={train.url.strip()!r}"
        inspect = "Inspect that identified failed run first"
    else:
        inspect = (
            "Run URL unavailable; inspect that exact combined-head revision "
            "with `yoke github-actions find-run <repo> <workflow-file> "
            "<commit-sha> --event merge_group --status failure --project "
            "<project>` (use the reported combined head as <commit-sha>)"
        )
    compared = f"lane head={lane_head!r}, current base={base_sha!r}"
    if trained_base:
        compared += f", trained base={trained_base!r}"
    else:
        compared += ", current base is an ancestor of the combined head"
    return (
        f"{FAILED_TRAIN_UNCHANGED}: pull request {pr_num!r} already has a "
        f"failed train for these unchanged inputs; {identity}; {compared}. "
        f"{inspect}. A failing or flaky test is a defect: fix it on the lane, "
        "commit, re-run the verification gate, then re-run yoke merge item. "
        "If this item's change did not cause it, file it (yoke feedback "
        "--to universe --category failed --evidence 'Flaky test: TEST, CI run URL, "
        "observed outcomes' then yoke feedback promote ENTRY --title 'Fix flaky TEST'), "
        "record the dependency, and park; the gate stays red until the fix lands. "
        "Do not use empty commits to re-run unchanged inputs."
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
    resolved = (
        list(parents)
        if parents is not None
        else _commit_parents(
            ctx,
            train_sha,
        )
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

    def refusal():
        return _refusal(
            pr_num,
            observed,
            lane_head=head,
            base_sha=current_base,
            trained_base=trained_base,
        )

    if trained_base:
        if current_base and current_base == trained_base:
            return refusal()
        return None
    if current_base and _base_covers_train(ctx, current_base, train_sha):
        return refusal()
    return None


__all__ = [
    "FAILED_TRAIN_UNCHANGED",
    "unchanged_failed_train_refusal",
]
