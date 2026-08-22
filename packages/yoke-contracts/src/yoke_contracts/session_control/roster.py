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
    "liveness",
    "relay",
    "messageability",
)


__all__ = ["SESSION_CONTROL_ROSTER_DISPLAY_FIELDS"]
