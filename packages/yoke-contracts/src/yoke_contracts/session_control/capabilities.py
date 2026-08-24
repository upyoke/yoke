"""Versioned harness capability facts used to compute messageability."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS


InterfaceClass = Literal["supported", "private", "none"]


@dataclass(frozen=True)
class SessionSurfaceCapability:
    minimum_version: str
    inject_events: tuple[str, ...]
    create: InterfaceClass
    message_active: InterfaceClass
    message_idle: InterfaceClass
    message_stopped: InterfaceClass

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["inject_events"] = list(self.inject_events)
        return payload


SESSION_SURFACE_CAPABILITIES: dict[str, SessionSurfaceCapability] = {
    "claude-cli": SessionSurfaceCapability(
        "2.1.238",
        ("UserPromptSubmit", "PreToolUse", "PostToolUse"),
        "supported",
        "private",
        "private",
        "supported",
    ),
    "claude-desktop": SessionSurfaceCapability(
        "1.32885.1",
        ("UserPromptSubmit", "PreToolUse", "PostToolUse"),
        "none",
        "private",
        "private",
        "none",
    ),
    "claude-vscode": SessionSurfaceCapability(
        "2.1.238",
        ("UserPromptSubmit", "PreToolUse", "PostToolUse"),
        "none",
        "supported",
        "private",
        "none",
    ),
    "codex-cli": SessionSurfaceCapability(
        "0.148.0-alpha.15",
        (
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PermissionRequest",
            "PostToolUse",
        ),
        "supported",
        "none",
        "none",
        "supported",
    ),
    "codex-desktop": SessionSurfaceCapability(
        "26.814.41407",
        (
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PermissionRequest",
            "PostToolUse",
        ),
        "supported",
        "supported",
        "supported",
        "supported",
    ),
    "codex-vscode": SessionSurfaceCapability(
        "0.148.0-alpha.15",
        (
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PermissionRequest",
            "PostToolUse",
        ),
        "none",
        "supported",
        "none",
        "none",
    ),
    "cursor-cli": SessionSurfaceCapability(
        "2026.08.11",
        ("SessionStart", "PostToolUse"),
        "supported",
        "none",
        "supported",
        "supported",
    ),
    "cursor-desktop": SessionSurfaceCapability(
        "3.17.8",
        ("SessionStart", "PostToolUse"),
        "none",
        "none",
        "none",
        "none",
    ),
}

if set(SESSION_SURFACE_CAPABILITIES) != set(KNOWN_SURFACE_LABELS):
    raise RuntimeError("session-control capability facts must cover every surface")


def capability_for_surface(surface: str | None) -> SessionSurfaceCapability | None:
    return SESSION_SURFACE_CAPABILITIES.get(str(surface or ""))


def capabilities_for_harness(harness_id: str) -> dict[str, dict[str, object]]:
    """Return serialized facts for one canonical harness family."""
    prefix = "claude-" if harness_id == "claude-code" else f"{harness_id}-"
    return {
        surface: capability.to_json()
        for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
        if surface.startswith(prefix)
    }


__all__ = [
    "SESSION_SURFACE_CAPABILITIES",
    "SessionSurfaceCapability",
    "capabilities_for_harness",
    "capability_for_surface",
]
