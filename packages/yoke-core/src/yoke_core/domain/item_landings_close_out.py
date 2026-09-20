"""Describing the landing close-out is finishing, and recording it.

Close-out already has to say which lane it is closing: either the landed-lane
path's answer, for a base branch that already holds the work, or one built
from the merge that just ran. Both routes to the base branch — the merge queue
and the standalone engine — arrive here with that identity resolved, and this
is the only place they both pass through, so it is the one writer of the
item's landing history. A second writer anywhere else could disagree with what
close-out believes it landed.

The append is idempotent on the landing identity, so a close-out re-entered
after a dead wait converges on the landing it already recorded. Only a
different merge identity is a second landing.

Recording is advisory and never unwinds a merge that has already landed: a
control-plane hiccup costs the audit trail one row, and refusing the close-out
over it would cost the item its terminal transition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.item_landings_schema import (
    ROUTE_FAST_FORWARD,
    ROUTE_MERGE_QUEUE,
    ROUTE_STANDALONE,
)
from yoke_core.domain.standalone_item_merge_landed import LandedLane

RECORD_FUNCTION_ID = "item_landings.record"


def landing_route(*, merge_sha: str, candidate_sha: str, pr_number: str) -> str:
    """How this landing reached the base branch.

    A landing with no merge commit distinct from the commit it carried is a
    fast-forward or a squash, whichever engine produced it: the landed commit
    is the only identity there is, and the route says so rather than implying
    a merge commit a reader could go looking for. Otherwise a pull request
    means the merge queue merged it, and anything else is the standalone
    engine's own merge commit.
    """
    if not merge_sha or merge_sha.strip().lower() == candidate_sha.strip().lower():
        return ROUTE_FAST_FORWARD
    return ROUTE_MERGE_QUEUE if pr_number else ROUTE_STANDALONE


def landing_time(*, repo_root: str, merge_sha: str, queue_landed_at: str) -> str:
    """When this landing happened, by the same precedence the item stamp uses.

    A queue landing observed on GitHub holds the moment the queue merged it,
    which outranks the merge commit's own committer time: the queue creates
    that commit when the train forms and merges it minutes later. Every other
    landing takes the commit's time, which for that boundary IS the landing.
    A landing nobody timed falls back to now, and says nothing stronger.
    """
    if queue_landed_at.strip():
        return queue_landed_at.strip()
    recorded = git.commit_time(repo_root, merge_sha) if repo_root else ""
    return recorded or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(item_id: int, payload: dict[str, Any]) -> str:
    """Append one landing. Returns an advisory note, empty on success."""
    try:
        response = call_dispatcher(
            function_id=RECORD_FUNCTION_ID,
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 - advisory, never fatal
        return f"landing not recorded: {exc}"
    if response.success:
        return ""
    detail = (
        response.error.message if response.error is not None
        else "landing write failed"
    )
    return f"landing not recorded: {detail}"


def close_out_lane(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    landed_lane: Optional[LandedLane],
    outcome: Any,
    queue_pr_number: str = "",
    queue_landed_at: str = "",
) -> tuple[LandedLane, str]:
    """The lane close-out is finishing, with its landing recorded.

    Returns the lane and an advisory note, empty when the landing was
    recorded or was already on the item's history.
    """
    lane = landed_lane or LandedLane(
        branch=branch,
        target=target,
        commit_sha=outcome.commit_sha,
        merge_sha=outcome.merge_sha,
        touched_files=tuple(outcome.touched_files),
        source="this merge",
    )
    candidate_sha = str(lane.commit_sha or "").strip()
    merge_sha = str(lane.merge_sha or "").strip()
    pr_number = str(queue_pr_number or getattr(outcome, "pr_num", "") or "").strip()
    identity = merge_sha or candidate_sha
    if not identity:
        return lane, (
            f"landing not recorded: close-out for branch {branch!r} on "
            f"{target!r} resolved neither a merge commit nor a candidate "
            "commit, so the landing has no identity to record it under. "
            "Re-run the merge once the lane resolves a commit the target "
            "does not already contain."
        )
    note = _record(
        item_id,
        {
            "merge_sha": identity,
            "candidate_sha": candidate_sha,
            "pr_number": pr_number,
            "target_branch": target,
            "route": landing_route(
                merge_sha=merge_sha,
                candidate_sha=candidate_sha,
                pr_number=pr_number,
            ),
            "landed_at": landing_time(
                repo_root=repo_root,
                merge_sha=identity,
                queue_landed_at=str(queue_landed_at or ""),
            ),
        },
    )
    return lane, note


__all__ = [
    "RECORD_FUNCTION_ID",
    "close_out_lane",
    "landing_route",
    "landing_time",
]
