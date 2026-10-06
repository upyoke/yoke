"""Explicit origin vocabulary for human-authored Fleet messages."""

from __future__ import annotations

from typing import Any, Literal, Mapping, get_args


SenderSurface = Literal[
    "web_form",
    "cli",
    "harness_session",
]
SENDER_SURFACES: tuple[str, ...] = get_args(SenderSurface)
(
    WEB_FORM_SENDER_SURFACE,
    CLI_SENDER_SURFACE,
    HARNESS_SESSION_SENDER_SURFACE,
) = SENDER_SURFACES


#: Function ids whose payload records the surface a person sent from.
SENDER_SURFACE_FUNCTIONS = frozenset(
    {"session_control.message.send", "session_control.launch.create"}
)


def with_web_form_sender_surface(
    function_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Stamp a browser workbench call's payload with its sending surface.

    A workbench host calls this on every browser envelope it dispatches;
    the payload's own claim is replaced, never trusted.
    """
    stamped = dict(payload)
    if function_id in SENDER_SURFACE_FUNCTIONS:
        stamped["sender_surface"] = WEB_FORM_SENDER_SURFACE
    return stamped


def sender_surface_label(value: str | None) -> str | None:
    """Return the operator-facing origin label for a stored surface."""
    labels = {
        WEB_FORM_SENDER_SURFACE: "dashboard",
        CLI_SENDER_SURFACE: "CLI",
        HARNESS_SESSION_SENDER_SURFACE: "harness session",
    }
    return labels.get(value) if value else None


__all__ = [
    "CLI_SENDER_SURFACE",
    "HARNESS_SESSION_SENDER_SURFACE",
    "SENDER_SURFACES",
    "SENDER_SURFACE_FUNCTIONS",
    "SenderSurface",
    "WEB_FORM_SENDER_SURFACE",
    "sender_surface_label",
    "with_web_form_sender_surface",
]
