"""Bring a project checkout's default branch current before work starts.

Every workflow prepares work from the project's default branch: a new lane
is cut from it, and laneless work runs on it in place. A checkout whose
default branch trails its remote starts that work on a stale base, and
nothing reveals the staleness until a merge conflicts or an already-fixed
defect reappears. This module answers, once per checkout per process,
whether that branch is current with the remote that tracks it, and brings
it current when that can be done without touching anything local.

Nothing here rewrites history, force-updates a local branch, or discards
work. Commits the remote lacks are preserved and reported rather than
replayed, and a working tree standing in the way of a fast-forward earns a
refusal naming git's own reason plus the recovery step. New lanes are cut
from the revision this module verified, so a lane is current even when the
local branch itself could not move.

Neither the remote name nor the branch name is assumed: the remote is the
one git records as tracking the branch, and the branch is the one the
caller's project declares, or the one the remote publishes as its default.
Git mechanics live in :mod:`yoke_core.domain.repo_upstream_git`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from yoke_core.domain import repo_upstream_git as upstream_git

# One network fetch per checkout per process: every preparation surface
# reads the same answer instead of each tool opening its own connection.
_CACHE: Dict[Tuple[str, str], "UpstreamFreshness"] = {}

STATE_CURRENT = "current"
STATE_FAST_FORWARDED = "fast_forwarded"
STATE_BEHIND_NOT_UPDATED = "behind_not_updated"
STATE_LOCAL_AHEAD = "local_ahead"
STATE_DIVERGED = "diverged"
STATE_FETCH_FAILED = "fetch_failed"
STATE_NO_REMOTE = "no_remote"
STATE_REMOTE_UNRESOLVED = "remote_unresolved"
STATE_UNREADABLE = "unreadable"

NOTE_PREFIX = "upstream freshness:"


@dataclass(frozen=True)
class UpstreamFreshness:
    """What the checkout's default branch is, relative to its remote.

    ``lane_base_ref`` is the revision new work must start from: the fetched
    upstream revision when it already contains everything local, and the
    local branch whenever local commits would otherwise be left behind.
    ``note`` names the observation and its recovery; ``needs_attention``
    marks the notes a caller surfaces as a warning rather than as progress;
    ``blocked`` marks the one case where an otherwise safe update was
    refused by local state.
    """

    state: str
    base_branch: str = ""
    remote: str = ""
    local_sha: str = ""
    upstream_sha: str = ""
    ahead: int = 0
    behind: int = 0
    lane_base_ref: str = ""
    note: str = ""
    needs_attention: bool = False
    blocked: bool = False


def refresh_base_branch(
    repo_root: str,
    base_branch: str = "",
    *,
    remote: str = "",
    use_cache: bool = True,
) -> UpstreamFreshness:
    """Fetch the remote default branch and bring the local one current.

    Safe to call from every preparation surface: the answer is cached per
    checkout and branch for the life of the process, so a preflight that
    also creates a lane fetches once rather than once per step.
    """
    if not repo_root:
        return _unreadable(base_branch, "no checkout root was given")
    if not base_branch:
        remote = remote or upstream_git.resolve_remote(repo_root)[0]
        base_branch = upstream_git.resolve_base_branch(repo_root, remote)
        if not base_branch:
            return _unreadable(
                base_branch,
                f"could not name the default branch of {repo_root}. Recovery: "
                "check out the default branch, or pass it explicitly.",
            )
    key = (repo_root, base_branch)
    if use_cache and key in _CACHE:
        return _CACHE[key]
    outcome = _evaluate(repo_root, base_branch, remote)
    _CACHE[key] = outcome
    return outcome


def reset_cache() -> None:
    """Forget every cached answer (test seam; one process, one fetch)."""
    _CACHE.clear()


def _unreadable(base_branch: str, detail: str) -> UpstreamFreshness:
    return UpstreamFreshness(
        state=STATE_UNREADABLE,
        base_branch=base_branch,
        lane_base_ref=base_branch,
        note=f"{NOTE_PREFIX} {detail}",
        needs_attention=True,
    )


def _evaluate(repo_root: str, base_branch: str, remote: str) -> UpstreamFreshness:
    configured = 0
    if not remote:
        remote, configured = upstream_git.resolve_remote(repo_root, base_branch)
    head = upstream_git.git(repo_root, "rev-parse", f"refs/heads/{base_branch}")
    if head.returncode != 0:
        return _unreadable(
            base_branch,
            f"{base_branch} is not a branch in {repo_root}: "
            f"{upstream_git.reason(head)}",
        )
    local_sha = upstream_git.out(head)
    if remote:
        return _compare_and_update(repo_root, base_branch, remote, local_sha)
    if configured == 0:
        return UpstreamFreshness(
            state=STATE_NO_REMOTE,
            base_branch=base_branch,
            local_sha=local_sha,
            lane_base_ref=base_branch,
        )
    return UpstreamFreshness(
        state=STATE_REMOTE_UNRESOLVED,
        base_branch=base_branch,
        local_sha=local_sha,
        lane_base_ref=base_branch,
        note=(
            f"{NOTE_PREFIX} none of the {configured} configured remotes is "
            f"recorded as tracking {base_branch}, so no upstream was read and "
            f"work starts from local {base_branch}. Recovery: `git -C "
            f"{repo_root} branch --set-upstream-to=<remote>/{base_branch} "
            f"{base_branch}`."
        ),
        needs_attention=True,
    )


def _compare_and_update(
    repo_root: str, base_branch: str, remote: str, local_sha: str
) -> UpstreamFreshness:
    fetched = upstream_git.fetch_branch(repo_root, remote, base_branch)
    if fetched.returncode != 0:
        return UpstreamFreshness(
            state=STATE_FETCH_FAILED,
            base_branch=base_branch,
            remote=remote,
            local_sha=local_sha,
            lane_base_ref=base_branch,
            note=(
                f"{NOTE_PREFIX} could not fetch {remote} {base_branch}: "
                f"{upstream_git.reason(fetched)}. Work starts from local "
                f"{base_branch}, which may be stale. Recovery: restore network "
                "access or git credentials and re-run, or continue knowingly "
                "offline."
            ),
            needs_attention=True,
        )
    tracking = upstream_git.tracking_ref(remote, base_branch)
    upstream = upstream_git.git(repo_root, "rev-parse", tracking)
    read, ahead, behind, detail = upstream_git.count_ahead_behind(
        repo_root, local_sha, tracking
    )
    if upstream.returncode != 0 or not read:
        return _unreadable(
            base_branch,
            f"fetched {remote} {base_branch} but could not compare it with the "
            f"local branch: {detail or upstream_git.reason(upstream)}",
        )
    upstream_sha = upstream_git.out(upstream)
    observed = {
        "base_branch": base_branch,
        "remote": remote,
        "local_sha": local_sha,
        "upstream_sha": upstream_sha,
        "ahead": ahead,
        "behind": behind,
    }
    if ahead:
        return _local_commits_kept(repo_root, observed)
    if not behind:
        return UpstreamFreshness(
            state=STATE_CURRENT, lane_base_ref=upstream_sha, **observed
        )
    updated, refusal = upstream_git.fast_forward(
        repo_root, base_branch, local_sha, upstream_sha
    )
    if updated:
        return UpstreamFreshness(
            state=STATE_FAST_FORWARDED,
            lane_base_ref=upstream_sha,
            note=(
                f"{NOTE_PREFIX} {base_branch} fast-forwarded {behind} commit(s) "
                f"to {remote}/{base_branch} ({upstream_sha[:12]}); new work "
                "starts from that revision."
            ),
            **observed,
        )
    return UpstreamFreshness(
        state=STATE_BEHIND_NOT_UPDATED,
        lane_base_ref=upstream_sha,
        note=(
            f"{NOTE_PREFIX} {base_branch} is {behind} commit(s) behind "
            f"{remote}/{base_branch} and was not updated: {refusal}. Nothing "
            f"local was changed. Recovery: commit or stash the changes in "
            f"{repo_root}, then re-run; a new lane started now is cut from the "
            f"fetched {remote}/{base_branch} ({upstream_sha[:12]}) instead."
        ),
        needs_attention=True,
        blocked=True,
        **observed,
    )


def _local_commits_kept(repo_root: str, observed: dict) -> UpstreamFreshness:
    """Report commits the remote lacks; never replay or discard them."""
    base_branch = observed["base_branch"]
    remote = observed["remote"]
    behind = observed["behind"]
    tail = (
        f"and is {behind} commit(s) behind; not updated. Recovery: `git -C "
        f"{repo_root} rebase {remote}/{base_branch} {base_branch}` (or merge), "
        "then re-run."
        if behind
        else "; nothing to fast-forward. Push them when they are ready."
    )
    return UpstreamFreshness(
        state=STATE_DIVERGED if behind else STATE_LOCAL_AHEAD,
        lane_base_ref=base_branch,
        note=(
            f"{NOTE_PREFIX} {base_branch} has {observed['ahead']} commit(s) "
            f"{remote}/{base_branch} does not {tail} Those commits are "
            f"preserved and work prepared now starts from local {base_branch}."
        ),
        needs_attention=True,
        **observed,
    )


__all__ = [
    "NOTE_PREFIX",
    "STATE_BEHIND_NOT_UPDATED",
    "STATE_CURRENT",
    "STATE_DIVERGED",
    "STATE_FAST_FORWARDED",
    "STATE_FETCH_FAILED",
    "STATE_LOCAL_AHEAD",
    "STATE_NO_REMOTE",
    "STATE_REMOTE_UNRESOLVED",
    "STATE_UNREADABLE",
    "UpstreamFreshness",
    "refresh_base_branch",
    "reset_cache",
]
