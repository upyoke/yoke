"""Bring a project checkout's default branch current before work starts.

Every workflow prepares work from the project's default branch: a new lane
is cut from it, and laneless work runs on it in place. A checkout whose
default branch trails its remote starts that work on a stale base, and
nothing reveals the staleness until a merge conflicts or an already-fixed
defect reappears. This module answers whether that branch is current with
the remote that tracks it, and brings it current when that can be done
without touching anything local.

**Freshness is established or preparation refuses.** A remote-backed
project whose remote cannot be read — the fetch failed, no remote is
recorded as tracking the branch, the branch or the comparison is
unreadable — reports ``verified=False`` and names no revision to start
from. There is no implicit fall back to the local branch, because "work
from whatever is on disk" is exactly the stale start this module exists to
prevent. A project with no remote at all is a different answer:
``no_remote`` is verified local-only work, and it says nothing.

Nothing here rewrites history, force-updates a local branch, or discards
work. Commits the remote lacks are preserved and reported rather than
replayed, and a working tree standing in the way of a fast-forward earns a
refusal naming git's own reason plus the recovery step. New lanes are cut
from the revision this module verified, so a lane is current even when the
local branch itself could not move.

Neither the remote name nor the branch name is assumed: the remote is the
one git records as tracking the branch, and the branch is the one the
caller's project declares, or the one the remote publishes as its default.
Git mechanics live in :mod:`yoke_cli.config.repo_upstream_git`.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterator, Tuple

from yoke_cli.config import repo_upstream_git as upstream_git

# Deduplication is scoped to one preparation, never to the process. A
# long-running API process prepares work repeatedly, and an answer cached
# for its lifetime would hand the second preparation a remote reading from
# hours earlier. Inside a scope the repeated reads of one preparation share
# one fetch; outside one, every call goes to the remote.
_SCOPE: contextvars.ContextVar[Dict[Tuple[str, str], "UpstreamFreshness"] | None] = (
    contextvars.ContextVar("repo_upstream_freshness_scope", default=None)
)

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

    ``verified`` is the gate: false means the remote could not be read at
    all, so nothing here describes the remote and no preparation should
    start. ``local_branch_current`` says whether the local branch itself
    now holds everything the remote has — false where it is behind and
    bringing it current would have meant touching local work.
    ``lane_base_ref`` is the revision new work must start from: the fetched
    upstream revision when it already contains everything local, the local
    branch where local commits would otherwise be left behind, and empty
    when nothing was verified. ``lane_base_is_current`` says whether that
    revision holds everything the remote has, which a diverged branch does
    not — a lane cut there would silently be missing the fetched commits,
    so it is the one established reading no lane may start from. ``note``
    names the observation and its recovery; ``needs_attention`` marks the
    notes a caller surfaces as a warning rather than as progress.
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
    verified: bool = False
    local_branch_current: bool = False
    lane_base_is_current: bool = False
    needs_attention: bool = False


@contextmanager
def preparation_scope() -> Iterator[None]:
    """Share one remote reading across the reads of one preparation.

    Enter this around a single preparation operation — resolving the base,
    creating the lane, reporting the outcome. Two preparations, even
    back to back in the same process, each get their own remote reading.
    """
    existing = _SCOPE.get()
    if existing is not None:
        yield
        return
    token = _SCOPE.set({})
    try:
        yield
    finally:
        _SCOPE.reset(token)


def refresh_base_branch(
    repo_root: str,
    base_branch: str = "",
    *,
    remote: str = "",
    use_cache: bool = True,
) -> UpstreamFreshness:
    """Fetch the remote default branch and bring the local one current.

    Reads the remote on every call unless an enclosing
    :func:`preparation_scope` already answered for this checkout and
    branch. Pass ``use_cache=False`` to force a fresh reading even inside
    a scope — what a caller re-reading a remote that just moved needs.
    """
    if not repo_root:
        return _unverified(
            STATE_UNREADABLE, base_branch, "no checkout root was given"
        )
    if not base_branch:
        resolved, configured = (
            (remote, 1) if remote else upstream_git.resolve_remote(repo_root)
        )
        if not resolved:
            return _no_remote_or_unresolved(repo_root, base_branch, configured)
        remote = resolved
        base_branch = upstream_git.resolve_base_branch(repo_root, remote)
        if not base_branch:
            return _unverified(
                STATE_UNREADABLE,
                base_branch,
                f"{remote} publishes no default branch for {repo_root}, and the "
                "checked-out branch is not a substitute for one. Recovery: `git "
                f"-C {repo_root} remote set-head {remote} --auto`, or name the "
                "branch explicitly.",
            )
    key = (repo_root, base_branch)
    scope = _SCOPE.get()
    if use_cache and scope is not None and key in scope:
        return scope[key]
    outcome = _evaluate(repo_root, base_branch, remote)
    if use_cache and scope is not None:
        scope[key] = outcome
    return outcome


def _unverified(state: str, base_branch: str, detail: str) -> UpstreamFreshness:
    """No remote reading, so no revision to start from and no work here."""
    return UpstreamFreshness(
        state=state,
        base_branch=base_branch,
        note=f"{NOTE_PREFIX} {detail}",
        needs_attention=True,
    )


def _no_remote_or_unresolved(
    repo_root: str, base_branch: str, configured: int
) -> UpstreamFreshness:
    if configured == 0:
        return UpstreamFreshness(
            state=STATE_NO_REMOTE,
            base_branch=base_branch,
            lane_base_ref=base_branch,
            verified=True,
            local_branch_current=True,
            lane_base_is_current=True,
        )
    return _unverified(
        STATE_REMOTE_UNRESOLVED,
        base_branch,
        f"none of the {configured} configured remotes is recorded as tracking "
        f"{base_branch or 'the default branch'}, so no upstream could be read. "
        f"Recovery: `git -C {repo_root} branch --set-upstream-to=<remote>/"
        f"{base_branch or '<branch>'} {base_branch or '<branch>'}`.",
    )


def _evaluate(repo_root: str, base_branch: str, remote: str) -> UpstreamFreshness:
    configured = 0
    if not remote:
        remote, configured = upstream_git.resolve_remote(repo_root, base_branch)
    if not remote:
        return _no_remote_or_unresolved(repo_root, base_branch, configured)
    head = upstream_git.git(repo_root, "rev-parse", f"refs/heads/{base_branch}")
    if head.returncode != 0:
        return _unverified(
            STATE_UNREADABLE,
            base_branch,
            f"{base_branch} is not a branch in {repo_root}: "
            f"{upstream_git.reason(head)}",
        )
    return _compare_and_update(repo_root, base_branch, remote, upstream_git.out(head))


def _compare_and_update(
    repo_root: str, base_branch: str, remote: str, local_sha: str
) -> UpstreamFreshness:
    fetched = upstream_git.fetch_branch(repo_root, remote, base_branch)
    if fetched.returncode != 0:
        return _unverified(
            STATE_FETCH_FAILED,
            base_branch,
            f"could not fetch {remote} {base_branch}: "
            f"{upstream_git.reason(fetched)}. Work does not start from the "
            "local branch on a failed fetch, because there is no evidence it "
            "is current. Recovery: restore network access or git credentials "
            "and re-run.",
        )
    tracking = upstream_git.tracking_ref(remote, base_branch)
    upstream = upstream_git.git(repo_root, "rev-parse", tracking)
    read, ahead, behind, detail = upstream_git.count_ahead_behind(
        repo_root, local_sha, tracking
    )
    if upstream.returncode != 0 or not read:
        return _unverified(
            STATE_UNREADABLE,
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
        "verified": True,
    }
    if ahead:
        return _local_commits_kept(repo_root, observed)
    if not behind:
        return UpstreamFreshness(
            state=STATE_CURRENT,
            lane_base_ref=upstream_sha,
            local_branch_current=True,
            lane_base_is_current=True,
            **observed,
        )
    updated, refusal = upstream_git.fast_forward(
        repo_root, base_branch, local_sha, upstream_sha
    )
    if updated:
        return UpstreamFreshness(
            state=STATE_FAST_FORWARDED,
            lane_base_ref=upstream_sha,
            local_branch_current=True,
            lane_base_is_current=True,
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
        lane_base_is_current=True,
        note=(
            f"{NOTE_PREFIX} {base_branch} is {behind} commit(s) behind "
            f"{remote}/{base_branch} and was not updated: {refusal}. Nothing "
            f"local was changed. Recovery: commit or stash the changes in "
            f"{repo_root}, then re-run; a new lane started now is cut from the "
            f"fetched {remote}/{base_branch} ({upstream_sha[:12]}) instead."
        ),
        needs_attention=True,
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
        local_branch_current=not behind,
        # Ahead-only local already contains every upstream commit, so a
        # lane cut from it is current. A diverged branch does not, and a
        # lane cut there would be missing the commits just fetched.
        lane_base_is_current=not behind,
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
    "preparation_scope",
    "refresh_base_branch",
]
