"""Open the pull request of a lane whose only landing blocker is integration.

An integration dependency holds the merge, not the work: the dependent
works, tests and opens its pull request now and merges only after its
predecessors do. ``yoke merge item`` therefore publishes such a lane before
it refuses — it pushes the branch and opens (or reuses) and records the
landing pull request, but never arms or enqueues it. Any other blocker
refuses with nothing published, and ``--check`` stays read-only.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_landing_readiness import LandingReadiness
from yoke_core.domain.merge_queue_landing_pull_request import (
    ensure_landing_pull_request,
)
from yoke_core.domain.merge_queue_route_selection import queue_lane_head
from yoke_core.domain.merge_worktree_lookup import _find_worktree
from yoke_core.domain.standalone_item_merge_lane import merge_source_lane

#: The gate name route admission gives the integration dependency refusal.
INTEGRATION_GATE = "integration dependency"
#: The refusal code that means the gate answered and found predecessors open;
#: an unreadable gate shares the gate name and publishes nothing.
BLOCKED_CODE = "integration_dependency_blocked:"


def held_only_by_integration(readiness: LandingReadiness) -> bool:
    """Whether every landing blocker is the integration dependency hold."""
    return bool(readiness.blockers) and all(
        blocker.gate == INTEGRATION_GATE
        and blocker.reason.startswith(BLOCKED_CODE)
        for blocker in readiness.blockers
    )


def publish_held_lane(
    item: dict[str, Any],
    readiness: LandingReadiness,
    *,
    ensure: Callable[..., tuple[str, Any, str]] = ensure_landing_pull_request,
) -> list[str]:
    """Push the lane and open its pull request; return the lines to report.

    The caller still refuses with the integration refusal afterwards, so a
    publish failure is reported beside it rather than replacing it.
    """
    public_ref = readiness.public_ref
    repo_root = str(readiness.repo_root)
    project = str((item.get("project") or {}).get("slug") or "")
    recorded = str((merge_source_lane(item) or {}).get("commit_sha") or "")
    lane_head, head_error = queue_lane_head(
        item_id=public_ref,
        branch=readiness.branch,
        target=readiness.target,
        repo_root=repo_root,
        project=project,
        commit_sha=recorded,
    )
    if head_error:
        return [f"pull request not opened: {head_error}"]
    ctx = MergeContext(
        args=MergeArgs(branch=readiness.branch, target=readiness.target),
        repo_root=repo_root,
        worktree_path=_find_worktree(readiness.branch, repo_root),
        project=project,
    )
    pr_num, error, record_warning = ensure(
        ctx, public_ref, lane_head=lane_head, item_public_ref=public_ref
    )
    lines = [f"warning: {record_warning}"] if record_warning else []
    if error or not pr_num:
        return [
            *lines,
            f"pull request not opened for {readiness.branch!r}: "
            f"{error or 'no pull request number returned'}. Fix that, then "
            f"re-run `yoke merge item {public_ref}` to open it.",
        ]
    return [
        *lines,
        f"pull request {pr_num} is open for {readiness.branch!r} at "
        f"{lane_head[:12]}, not armed or queued: only the merge is held.",
    ]


__all__ = ["held_only_by_integration", "publish_held_lane"]
