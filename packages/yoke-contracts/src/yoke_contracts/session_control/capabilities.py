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
#: Who may resume a session on this surface. ``native`` means Yoke may
#: drive the harness's own resume; ``operator`` means only the person
#: sitting in front of it may, because resuming an open desktop window
#: headlessly forks the transcript they are reading — the woken turns
#: land in a copy of the conversation the app only shows on refresh, and
#: the next sentence they type continues the branch they can see.
WakeAuthority = Literal["native", "operator"]
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
    wake_authority: WakeAuthority = "native"
    native_create_timeout_seconds: int | None = None

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["inject_events"] = list(self.inject_events)
        payload["liveness_process_names"] = list(self.liveness_process_names)
        if self.native_create_timeout_seconds is None:
            payload.pop("native_create_timeout_seconds")
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
        native_create_timeout_seconds=180,
    ),
    "claude-desktop": SessionSurfaceCapability(
        "1.32885.1",
        ("UserPromptSubmit", "PreToolUse", "PostToolUse"),
        "none",
        "private",
        "private",
        "none",
        wake_authority="operator",
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
        wake_authority="operator",
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
        wake_authority="operator",
    ),
}

if set(SESSION_SURFACE_CAPABILITIES) != set(KNOWN_SURFACE_LABELS):
    raise RuntimeError("session-control capability facts must cover every surface")


def capability_for_surface(surface: str | None) -> SessionSurfaceCapability | None:
    return SESSION_SURFACE_CAPABILITIES.get(str(surface or ""))


def surface_wake_authority(surface: str | None) -> WakeAuthority:
    """Return who may resume one surface: Yoke natively, or its operator.

    A surface nobody has declared reads ``native``, because every other
    refusal in this contract already covers an unknown surface; this fact
    exists to name the declared exception, not to invent a second one.
    """
    capability = capability_for_surface(surface)
    return capability.wake_authority if capability is not None else "native"


def native_wake_supported(surface: str | None) -> bool:
    """Whether Yoke may resume this surface without a person in the loop."""
    return surface_wake_authority(surface) == "native"


def operator_wake_instruction(surface: str | None) -> str:
    """The one sentence every surface teaches about an operator-woken wake."""
    return (
        f"Yoke never resumes a {surface or 'desktop'} session: a native resume "
        "forks the transcript its operator is reading. The message stays "
        "pending and is delivered the moment the operator types anything in "
        "that chat, so ask them to open it and type."
    )


def native_create_timeout_seconds(surface: str | None) -> int | None:
    """Return the manifest-owned soft create bound for one native surface."""
    capability = capability_for_surface(surface)
    return capability.native_create_timeout_seconds if capability else None


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
    "WakeAuthority",
    "capabilities_for_harness",
    "capability_for_surface",
    "liveness_process_names",
    "native_wake_supported",
    "operator_wake_instruction",
    "native_create_timeout_seconds",
    "stop_denial_continuation_supported",
    "surface_wake_authority",
]
