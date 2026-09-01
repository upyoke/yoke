"""Explicit origin vocabulary for human-authored Fleet messages."""

from __future__ import annotations

from typing import Literal, get_args


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
    "SenderSurface",
    "WEB_FORM_SENDER_SURFACE",
    "sender_surface_label",
]
