"""Versioned harness capability facts used to compute messageability."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from yoke_contracts.executor_labels import (
    KNOWN_SURFACE_LABELS,
    canonical_harness_id,
    surface_alias,
)


InterfaceClass = Literal["supported", "private", "none"]
CURSOR_LIVENESS_PROCESS_NAMES = ("cursor-agent", "cursor")


@dataclass(frozen=True)
class SessionSurfaceCapability:
    minimum_version: str
    inject_events: tuple[str, ...]
    create: InterfaceClass
    message_active: InterfaceClass
    message_idle: InterfaceClass
    message_stopped: InterfaceClass
    stop_denial_continuation: InterfaceClass = "supported"
    relay_stop_denial_continuation: InterfaceClass = "supported"
    liveness_process_names: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["inject_events"] = list(self.inject_events)
        payload["liveness_process_names"] = list(self.liveness_process_names)
        return payload


SESSION_SURFACE_CAPABILITIES: dict[str, SessionSurfaceCapability] = {
    "claude-cli": SessionSurfaceCapability(
        "2.1.238",
        ("UserPromptSubmit", "PreToolUse", "PostToolUse"),
        "supported",
        "private",
        "private",
        "supported",
        relay_stop_denial_continuation="none",
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
        relay_stop_denial_continuation="none",
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
        "none",
        "none",
        "none",
        "none",
        relay_stop_denial_continuation="none",
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
        stop_denial_continuation="none",
        relay_stop_denial_continuation="none",
        liveness_process_names=CURSOR_LIVENESS_PROCESS_NAMES,
    ),
    "cursor-desktop": SessionSurfaceCapability(
        "3.17.8",
        ("SessionStart", "PostToolUse"),
        "none",
        "none",
        "none",
        "none",
        stop_denial_continuation="none",
        relay_stop_denial_continuation="none",
    ),
}

if set(SESSION_SURFACE_CAPABILITIES) != set(KNOWN_SURFACE_LABELS):
    raise RuntimeError("session-control capability facts must cover every surface")


def capability_for_surface(surface: str | None) -> SessionSurfaceCapability | None:
    return SESSION_SURFACE_CAPABILITIES.get(str(surface or ""))


def _capabilities_for_executor(
    executor: str | None,
) -> tuple[SessionSurfaceCapability, ...]:
    direct = capability_for_surface(executor)
    if direct is not None:
        return (direct,)
    try:
        harness_id = canonical_harness_id(executor)
    except ValueError:
        return ()
    prefix = "claude-" if harness_id == "claude-code" else f"{harness_id}-"
    return tuple(
        capability
        for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
        if surface.startswith(prefix)
    )


def _surface_for_context(
    executor: str | None,
    surface: str | None,
) -> str | None:
    alias = surface_alias(surface)
    if alias is not None:
        return alias
    token = str(surface or "").strip().lower().replace("_", "-")
    if token not in {"cli", "desktop", "vscode"}:
        return None
    try:
        harness_id = canonical_harness_id(executor)
    except ValueError:
        return None
    prefix = "claude" if harness_id == "claude-code" else harness_id
    candidate = f"{prefix}-{token}"
    return candidate if candidate in SESSION_SURFACE_CAPABILITIES else None


def stop_denial_continuation_supported(
    executor: str | None,
    surface: str | None = None,
    *,
    relay_launched: bool = False,
) -> bool:
    """Whether denying Stop can make this session continue the same turn."""
    resolved = _surface_for_context(executor, surface)
    capabilities = (
        (SESSION_SURFACE_CAPABILITIES[resolved],)
        if resolved is not None
        else _capabilities_for_executor(executor)
    )
    return not capabilities or all(
        capability.stop_denial_continuation == "supported"
        and (
            not relay_launched
            or capability.relay_stop_denial_continuation == "supported"
        )
        for capability in capabilities
    )


def liveness_process_names(executor: str | None) -> tuple[str, ...]:
    """Process basenames a surface permits as liveness-only anchors."""
    names = {
        name
        for capability in _capabilities_for_executor(executor)
        for name in capability.liveness_process_names
    }
    return tuple(sorted(names))


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
    "liveness_process_names",
    "stop_denial_continuation_supported",
]
