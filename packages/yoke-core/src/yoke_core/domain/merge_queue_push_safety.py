"""Refuse to publish a lane commit against a candidate the queue still holds.

A pull request armed or enqueued for one head keeps landing that head. A
push that moves the branch underneath it does not move the candidate: the
queue merges what it already took, and the pushed commit lands on no branch
the base ever absorbed — a silent orphan found later by hand, if at all.

Every path that publishes a lane branch runs this check, because they share
one publish (:func:`yoke_core.domain.qa_case_ci_lane.push_lane`). The
refusal names what GitHub reported and the one recovery that makes the push
safe: hold the candidate (``yoke github merge-queue hold``), which clears
the arming and removes the entry and verifies both, then publish and re-arm
explicitly. Nothing here mutates the landing — holding is the holder's
deliberate act, not a side effect of wanting to push.

:class:`LanePublishBlocked` is its own error so a caller can report it
verbatim instead of folding it into the transport-failure advice a refused
push otherwise carries; a force-push is exactly the wrong recovery here.

The check is scoped to projects that actually land through a queue, and to
a candidate whose head differs from the commit being published: republishing
the exact commit the queue is already holding changes nothing.

Every read on the way to that answer either succeeds or refuses. A project
that does not declare the queue, and a listing that came back empty, are
answers; a capability probe that errored, a listing that could not be read,
and a queue that could not be read back are not, and treating them as "no
candidate" is what would let an outage wave through the exact push this
guard exists to stop.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.merge_queue_hold import REARM_RECOVERY
from yoke_core.domain.merge_queue_readiness import read_merge_queue_readiness
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.engines.merge_worktree_pr_discovery import (
    base_ref,
    list_branch_pull_requests,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

#: The command that makes a live candidate safe to correct.
HOLD_COMMAND = "yoke github merge-queue hold <item>"


class LanePublishBlocked(QaCaseExecutionError):
    """The lane cannot be published because its candidate is still live."""


def _same_commit(left: str, right: str) -> bool:
    a, b = left.strip().lower(), right.strip().lower()
    return bool(a) and bool(b) and a == b


def _unreadable(what: str, detail: str, *, branch: str, head_sha: str) -> str:
    """Refuse a push whose safety could not be established."""
    reason = detail or "no detail reported"
    return (
        f"{what} for {branch!r} could not be read ({reason}), so whether a "
        "landing is holding this branch is unknown. Publishing "
        f"{head_sha or 'the lane'} could orphan the commit under a landing "
        "already in flight. Re-run once the read succeeds, or hold the "
        f"candidate explicitly: {HOLD_COMMAND}."
    )


def _live_candidate_refusal(
    readiness, *, branch: str, head_sha: str, pr_number: str
) -> str:
    return (
        f"pull request {pr_number} is still holding a landing for {branch!r} "
        f"at head {readiness.head_sha or 'unreported'} "
        f"(queue-holding={readiness.queue_holding}, "
        f"queue-entry={readiness.queue_entry_state}, "
        f"merge-when-ready={readiness.merge_when_ready}). Publishing "
        f"{head_sha or 'a new commit'} would leave the queue landing the head "
        "it already took and the new commit on no branch. Hold it first — "
        f"{HOLD_COMMAND} — which clears the arming, removes the entry, and "
        f"verifies both; then {REARM_RECOVERY}."
    )


def lane_publish_refusal(
    *,
    project: str,
    checkout: Path,
    branch: str,
    target: str,
    head_sha: str = "",
) -> str:
    """Why publishing ``head_sha`` on ``branch`` would race a live landing.

    Returns ``""`` when the push is safe. An empty ``head_sha`` means the
    caller is publishing whatever the branch points at and cannot compare,
    so any live candidate counts as a different one.
    """
    if not project:
        return ""
    from yoke_core.domain.merge_queue_route_selection import (
        project_declares_merge_queue,
    )

    declared, probe_error = project_declares_merge_queue(project)
    if probe_error:
        return _unreadable(
            f"the merge-queue capability of project {project!r}",
            probe_error,
            branch=branch,
            head_sha=head_sha,
        )
    if not declared:
        return ""
    ctx = MergeContext(
        args=MergeArgs(branch=branch, target=target),
        project=project,
        repo_root=str(checkout),
    )
    # Filtered by base as well as head: GitHub allows one open pull request
    # per head AND base, so a head-only listing can hold several rows and the
    # first is not necessarily the landing onto this target.
    listing = list_branch_pull_requests(
        ctx, query={"state": "open", "base": target}
    )
    if not listing.readable:
        return _unreadable(
            f"the open pull requests onto {target}",
            listing.error,
            branch=branch,
            head_sha=head_sha,
        )
    for row in listing.rows:
        if base_ref(row) != target:
            continue
        pr_number = str(row.get("number") or "").strip()
        if not pr_number:
            return _unreadable(
                f"a pull request onto {target}",
                "the listing row carries no number",
                branch=branch,
                head_sha=head_sha,
            )
        readiness = read_merge_queue_readiness(
            ctx, pr_number=pr_number, target=target
        )
        if readiness.merged or _same_commit(readiness.head_sha, head_sha):
            continue
        if not readiness.queue_readable:
            return _unreadable(
                f"pull request {pr_number} against the {target} queue",
                "; ".join(readiness.warnings),
                branch=branch,
                head_sha=head_sha,
            )
        if readiness.armed or readiness.has_queue_entry:
            return _live_candidate_refusal(
                readiness, branch=branch, head_sha=head_sha, pr_number=pr_number
            )
    return ""


def require_publishable_lane(
    *,
    project: str,
    checkout: Path,
    branch: str,
    target: str,
    head_sha: str = "",
) -> None:
    """Raise :class:`LanePublishBlocked` when the candidate is still live."""
    refusal = lane_publish_refusal(
        project=project,
        checkout=checkout,
        branch=branch,
        target=target,
        head_sha=head_sha,
    )
    if refusal:
        raise LanePublishBlocked(refusal)


__all__ = [
    "HOLD_COMMAND",
    "LanePublishBlocked",
    "lane_publish_refusal",
    "require_publishable_lane",
]
