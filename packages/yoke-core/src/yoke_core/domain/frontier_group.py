"""One home section per item, independent of dependency-graph references."""

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.item_flags import is_blocked, is_frozen


def frontier_group(
    item_state: Mapping[str, Any],
    holder_states: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Choose a total, exclusive home from workflow and shared session facts."""
    row = item_state
    next_actor = row.get("next_actor") or {}
    reason = next_actor.get("reason") or "ready_without_holder"

    def home(section, *, activity=None, why=None):
        return {"section": section, "activity": activity, "reason": why or reason}

    if row.get("finished"):
        return home("done", why="item_finished")
    if row.get("release_stage"):
        return home("release", why="awaiting_delivery")
    if is_frozen(row.get("frozen")) or is_blocked(row.get("blocked")):
        return home("on_hold", why=row.get("blocked_reason") or "item_on_hold")
    holders = [s for s in holder_states if s.get("status") != "ended"]
    if holders:
        working = any(s.get("status") == "working" for s in holders)
        return home("in_progress", activity="working" if working else "waiting")
    if row.get("terminal") or row.get("exceptional") or row.get("needs_spec"):
        return home(
            "on_hold", why="needs_spec" if row.get("needs_spec") else "work_halted"
        )
    if row.get("dependency_holds_pickup"):
        return home("waiting")
    if next_actor.get("actor") in {"operator", "ci_or_deploy"}:
        return home("on_hold")
    return home("ready")
