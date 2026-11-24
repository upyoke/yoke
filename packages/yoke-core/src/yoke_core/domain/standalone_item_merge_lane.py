"""Resolve the standalone merge source from the item's active worktree lane.

Released ``item_worktrees`` rows are history. Walking them in list order can
report ``already_merged`` from a stale HEAD that is already on the target
while the live lane is never considered.

Among several active lanes, the lane whose head is the queued pull request's
head is the source: that is the commit the queue holds or merged. Proving or
recording any other lane, even the integration lane, verifies a commit that
is not landing.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.refusal_recovery import compose_refusal

_ACTIVE = "active"
_RELEASED = "released"


def _state(lane: dict[str, Any]) -> str:
    value = str(lane.get("state") or _ACTIVE).strip()
    return value or _ACTIVE


def active_lanes(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Worktree records that may supply the merge source."""
    return [lane for lane in item.get("worktrees") or [] if _state(lane) != _RELEASED]


def _queued_head(item: dict[str, Any]) -> str:
    """The pull-request head the item's landing record names, if any."""
    return str((item.get("merge_queue") or {}).get("head_sha") or "").strip()


def _merge_lane_key(lane: dict[str, Any]) -> tuple:
    return lane.get("id"), lane.get("branch"), lane.get("path")


def merge_source_lane(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The sole active lane, the lane at the queued head, or the integration lane."""
    lanes = active_lanes(item)
    selected = item.get("_selected_merge_lane")
    if selected is not None:
        return next((lane for lane in lanes if _merge_lane_key(lane) == selected), None)
    if len(lanes) == 1:
        return lanes[0]
    queued_head = _queued_head(item)
    queued_lanes = [
        lane
        for lane in lanes
        if queued_head and str(lane.get("commit_sha") or "").strip() == queued_head
    ]
    if len(queued_lanes) == 1:
        return queued_lanes[0]
    integration_lanes = [
        lane
        for lane in lanes
        if str(lane.get("lane_role") or "").strip() == "integration"
    ]
    return integration_lanes[0] if len(integration_lanes) == 1 else None


def lane_resolution_error(item: dict[str, Any]) -> str:
    """Named refusal when the active-lane source is missing or ambiguous."""
    lanes = active_lanes(item)
    if merge_source_lane(item) is not None:
        return ""
    if not lanes:
        return (
            "no active worktree lane; merge source is the active lane, never "
            "a released record. If the branch already landed, retry "
            "`yoke merge item` so close-out recovers from the merge receipt"
        )
    labels = []
    for lane in lanes:
        branch = str(lane.get("branch") or "").strip() or "(unnamed)"
        role = str(lane.get("lane_role") or "").strip()
        labels.append(f"{branch} ({role})" if role else branch)
    queued_head = _queued_head(item) or "none recorded"
    return (
        "multiple active worktree lanes: "
        + ", ".join(labels)
        + compose_refusal(
            f"; none is at the queued pull-request head ({queued_head}) and there is no single integration lane, so the merge source is not chosen first-wins.",
            recovery=(
                "queue the landing pull request from the lane that carries the work, or "
                "keep exactly one active integration lane, then retry `yoke merge item`"
            ),
        )
    )


def lane_branch(item: dict[str, Any], public_ref: str) -> str:
    """Branch of the resolved active lane, else the item-ref recovery key.

    The fallback is the receipt lookup key when no active lane exists; it is
    not a merge source. Callers still refuse via :func:`lane_resolution_error`
    before merging.
    """
    lane = merge_source_lane(item)
    if lane is not None:
        branch = str(lane.get("branch") or "").strip()
        if branch:
            return branch
    recorded = str(item.get("worktree") or "").strip()
    return recorded if recorded and recorded != "null" else public_ref


def lane_path(item: dict[str, Any]) -> str:
    """Recorded path of the resolved active lane, if any."""
    lane = merge_source_lane(item)
    if lane is None:
        return ""
    return str(lane.get("path") or "").strip()


def stale_head_note(item: dict[str, Any], *, as_json: bool = True) -> str:
    from yoke_core.domain.lane_head_record import local_lane_head

    lane = merge_source_lane(item)
    if lane is None:
        return ""
    head, error = local_lane_head(lane)
    recorded = str(lane.get("commit_sha") or "")
    if error or not head or head == recorded:
        return ""
    revisions = f"lane at {head}, record at {recorded or '(none)'}"
    if as_json:
        return f"lane head stale: {revisions}; the merge will record the lane head"
    return f"record the stale lane head ({revisions})"


def refresh_recorded_head(item: dict[str, Any], resolve_item):
    """Record the local merge source before commit-bound readiness reads."""
    from yoke_core.domain.lane_head_record import reconcile_lane_head

    lane = merge_source_lane(item)
    if lane is None:
        return item, ""
    project = str((item.get("project") or {}).get("slug") or "")
    head, error = reconcile_lane_head(project, lane)
    if error or not head:
        return item, error
    refreshed, error = resolve_item()
    if refreshed:
        # A moved queued lane no longer matches the queue's old commit.
        # Keep the selected lane so readiness can judge that mismatch.
        refreshed = {**refreshed, "_selected_merge_lane": _merge_lane_key(lane)}
    current = merge_source_lane(refreshed) if refreshed else None
    if error or current is None or current.get("commit_sha") != head:
        return item, compose_refusal(
            f"lane_head_unrecorded: {error or 'recorded candidate does not match lane HEAD'}",
            recovery="rerun the same command",
        )
    return refreshed, ""


__all__ = [
    "active_lanes",
    "lane_branch",
    "lane_path",
    "lane_resolution_error",
    "merge_source_lane",
    "refresh_recorded_head",
    "stale_head_note",
]
