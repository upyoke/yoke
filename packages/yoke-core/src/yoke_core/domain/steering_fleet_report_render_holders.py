"""Render a holder's shared intent, next actor and message recovery."""

from yoke_core.domain.steering_fleet_report_holders import ClaimHolder
from yoke_core.domain.steering_fleet_report_render_text import (
    SECTION_LIMIT,
    capped,
    minutes,
)


def holder_lines(holders: tuple[ClaimHolder, ...], *, idle: bool = False) -> list[str]:
    lines = []
    for holder in holders[:SECTION_LIMIT]:
        line = (
            f"  {holder.public_ref}  session {holder.session_id}  mode "
            f"{holder.mode or 'unset'}  quiet {minutes(holder.idle_seconds)}"
        )
        intent = holder.session_state.get("intent", {})
        if intent.get("state") in {"parked", "awaiting"}:
            line += (
                f", {intent['state']} — {intent.get('reason') or 'reason not declared'}"
            )
        elif holder.quiet_reason:
            line += f", {holder.quiet_reason}"
        if holder.next_actor:
            next_action = holder.next_actor
            people = ", ".join(
                person["name"]
                for person in next_action.get("people", [])
                if person.get("name")
            )
            line += (
                f"  next: {people or next_action['actor']} — {next_action['reason']}"
            )
        if holder.hand_started:
            line += "  hand-started (operator origin)"
        line += f"  {holder.message_delivery}"
        if idle:
            line += f"  message it `yoke say --item {holder.public_ref} --stdin`"
        lines.append(line)
    return capped(lines, len(holders))
