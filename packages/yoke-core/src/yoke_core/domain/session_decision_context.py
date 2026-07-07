"""Shared context helpers for session next-action decisions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .session_contract import FrontierState


def _lane_filtered_note(count: int) -> str:
    return (
        f"{count} item(s) exist on the frontier but were "
        "filtered by lane policy — they may be runnable on another lane."
    )


def _apply_lane_filtered_signal(
    ctx: Dict[str, Any],
    frontier: FrontierState,
) -> Dict[str, Any]:
    if frontier.lane_filtered_count:
        ctx["lane_filtered_count"] = frontier.lane_filtered_count
        ctx["lane_filtered_note"] = _lane_filtered_note(frontier.lane_filtered_count)
        if frontier.lane_filtered_items:
            ctx["lane_filtered_items"] = list(frontier.lane_filtered_items)
    return ctx


def _compute_lane_filtered_paths(
    items: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Group filtered items by required path with counts.

    Deterministic order by path so the operator-facing rendering and tests see
    a stable view.
    """
    if not items:
        return []
    counts: Dict[str, int] = {}
    for entry in items:
        path = str(entry.get("required_path") or "unknown")
        counts[path] = counts.get(path, 0) + 1
    return [
        {"required_path": path, "count": count}
        for path, count in sorted(counts.items())
    ]


def build_no_lane_compatible_work_context(
    frontier: FrontierState,
    actual_lane: str,
) -> Dict[str, Any]:
    """Assemble the WAIT context for the filtered-empty lane case.

    Carries ``actual_lane``, the standard ``lane_filtered_*`` keys via
    :func:`_apply_lane_filtered_signal`, and a compact ``lane_filtered_paths``
    view derived from the filtered item detail.
    """
    ctx: Dict[str, Any] = {
        "wait_reason": "no_lane_compatible_work",
        "actual_lane": actual_lane,
    }
    _apply_lane_filtered_signal(ctx, frontier)
    filtered_items = list(frontier.lane_filtered_items or [])
    ctx["lane_filtered_items"] = filtered_items
    ctx["lane_filtered_paths"] = _compute_lane_filtered_paths(filtered_items)
    return ctx
