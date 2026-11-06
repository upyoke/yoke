"""Shared next-action projection from durable facts, independent of harness."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.timestamps import temporal_wire
from yoke_contracts.item_flags import is_frozen, is_blocked


def action(actor: str, reason: str, since: Any = None, **details: Any) -> dict:
    return temporal_wire(dict(actor=actor, reason=reason, since=since, **details))


def session_next_actor(row: Mapping[str, Any], *, presence: str) -> dict:
    """A named external obligation wins over the session's ability to run."""
    if presence == "ended":
        return action(
            "nobody", "session_ended", row.get("terminated_at") or row.get("ended_at")
        )
    for key in ("pending_decision", "dependency_wait", "ci_wait", "deployment_wait"):
        if row.get(key):
            return dict(row[key])
    wait = row.get("declared_wait") or {}
    if isinstance(wait, Mapping) and wait.get("kind") != "turn_posture":
        who = wait.get("awaiting_who")
        if wait.get("kind") == "dependency":
            return action(
                "another_item",
                wait.get("reason") or "dependency_unsatisfied",
                wait.get("since"),
                blocking_item=wait.get("blocking_item"),
            )
        if who in {"operator", "parent_or_steering", "another_item", "ci_or_deploy"}:
            return action(who, wait.get("reason") or "declared_wait", wait.get("since"))
    reason = row.get("quiet_reason")
    if row.get("mode") == "parked":
        return action(
            "parent_or_steering",
            reason or "parked_session_needs_direction",
            row.get("turn_posture_at"),
        )
    if presence == "gone":
        return action(
            "parent_or_steering",
            "session_process_gone",
            row.get("native_process_gone_at"),
        )
    return action("this_session", "session_can_continue", row.get("turn_posture_at"))


def item_next_actor(
    row: Mapping[str, Any], *, holder: Mapping[str, Any] | None = None
) -> dict:
    if row.get("terminal"):
        return action(
            "nobody", "item_terminal", row.get("finished_at") or row.get("updated_at")
        )
    for key in ("pending_decision", "dependency_wait", "ci_wait", "deployment_wait"):
        if row.get(key):
            return dict(row[key])
    if is_frozen(row.get("frozen")) or is_blocked(row.get("blocked")):
        return action(
            "parent_or_steering",
            row.get("blocked_reason") or "item_on_hold",
            row.get("updated_at"),
        )
    if holder:
        return session_next_actor(
            holder, presence=str(holder.get("presence") or "present")
        )
    return action(
        "parent_or_steering",
        "ready_without_holder",
        row.get("updated_at") or row.get("created_at"),
    )
