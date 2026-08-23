"""Canonical bootstrap teaching for Fleet message ownership and receipts."""

from __future__ import annotations


FLEET_MESSAGE_RECIPE = """yoke sessions list --liveness active
yoke say --preview --session SESSION-ID
printf '%s\\n' 'MESSAGE' | yoke say --session SESSION-ID --stdin
yoke messages list --recipient-session CURRENT-SESSION-ID --state injected
yoke messages get MESSAGE-ID
yoke messages acknowledge MESSAGE-ID"""
FLEET_UNDELIVERED_CANCEL_RECIPE = (
    "# Top-level sender recovery for an undelivered message:\n"
    "yoke messages cancel MESSAGE-ID"
)
FLEET_MESSAGE_BOOTSTRAP_RECIPE = "\n\n".join(
    (FLEET_MESSAGE_RECIPE, FLEET_UNDELIVERED_CANCEL_RECIPE)
)

TOP_LEVEL_FLEET_OWNERSHIP = (
    "Only the registered top-level session may send, acknowledge, or cancel Fleet "
    "messages or handle Fleet wake requests."
)
SUBAGENT_FLEET_GUIDANCE = (
    "In-process subagents see receipts shared with their parent read-only and "
    "communicate with the parent through the harness-native parent/subagent channel. "
    "They never send, acknowledge, or cancel Fleet messages or handle Fleet wake "
    "requests. Independently launched top-level workers remain Fleet participants."
)
FLEET_OWNERSHIP_GUIDANCE = f"{TOP_LEVEL_FLEET_OWNERSHIP} {SUBAGENT_FLEET_GUIDANCE}"
FLEET_MESSAGE_WORKFLOW_HELP = "\n\n".join(
    (
        "Top-level Fleet workflow:\n" + FLEET_MESSAGE_BOOTSTRAP_RECIPE,
        FLEET_OWNERSHIP_GUIDANCE,
    )
)


__all__ = [
    "FLEET_MESSAGE_BOOTSTRAP_RECIPE",
    "FLEET_MESSAGE_RECIPE",
    "FLEET_MESSAGE_WORKFLOW_HELP",
    "FLEET_OWNERSHIP_GUIDANCE",
    "FLEET_UNDELIVERED_CANCEL_RECIPE",
    "SUBAGENT_FLEET_GUIDANCE",
    "TOP_LEVEL_FLEET_OWNERSHIP",
]
