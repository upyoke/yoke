"""Shared field contract for the compact fleet-session roster."""

from __future__ import annotations


SESSION_CONTROL_ROSTER_DISPLAY_FIELDS = (
    "session_id",
    "project",
    "claims",
    "focus",
    "role",
    "worktree",
    "executor",
    "executor_surface",
    "executor_version",
    "machine_id",
    "machine_name",
    "liveness",
    "turn_posture",
    "resume_state",
    "relay",
    "messageability",
    "latest_message",
    "end_blocker",
    "effective_stale_ttl_minutes",
    "stale_eligible_at",
    "declared_wait",
    "stale_alive_probe",
    "steering_scope",
    "primary_item_stages",
)


__all__ = ["SESSION_CONTROL_ROSTER_DISPLAY_FIELDS"]
