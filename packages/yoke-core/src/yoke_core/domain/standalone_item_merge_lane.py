"""Resolve the standalone merge source from the item's active worktree lane.

Released ``item_worktrees`` rows are history. Walking them in list order can
report ``already_merged`` from a stale HEAD that is already on the target
while the live lane is never considered.
"""

from __future__ import annotations

from typing import Any, Optional

_ACTIVE = "active"
_RELEASED = "released"


def _state(lane: dict[str, Any]) -> str:
    value = str(lane.get("state") or _ACTIVE).strip()
    return value or _ACTIVE


def active_lanes(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Worktree records that may supply the merge source."""
    return [
        lane
        for lane in item.get("worktrees") or []
        if _state(lane) != _RELEASED
    ]


def merge_source_lane(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The sole active lane, or the sole integration lane among many."""
    lanes = active_lanes(item)
    if len(lanes) == 1:
        return lanes[0]
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
    return (
        "multiple active worktree lanes: "
        + ", ".join(labels)
        + "; refuse first-wins"
    )


def lane_branch(item: dict[str, Any], item_ref: str) -> str:
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
    return recorded if recorded and recorded != "null" else item_ref


def lane_path(item: dict[str, Any]) -> str:
    """Recorded path of the resolved active lane, if any."""
    lane = merge_source_lane(item)
    if lane is None:
        return ""
    return str(lane.get("path") or "").strip()


__all__ = [
    "active_lanes",
    "lane_branch",
    "lane_path",
    "lane_resolution_error",
    "merge_source_lane",
]
