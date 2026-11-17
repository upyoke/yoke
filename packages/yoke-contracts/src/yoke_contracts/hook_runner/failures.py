"""Shared diagnostic contract for hook-chain module failures."""

from __future__ import annotations

from collections.abc import Iterable

from yoke_contracts.hook_diagnostics import format_hook_diagnostic


FAILURE_PREFIX = "failure:"
GUARD_FAILURE_MARKER = "YOKE_HOOK_GUARD_FAILURE"


def failure_markers(degraded: Iterable[object]) -> tuple[str, ...]:
    """Return ordered, well-formed guard-failure markers."""
    return tuple(
        marker
        for marker in degraded
        if isinstance(marker, str) and marker.startswith((FAILURE_PREFIX, "session_registration_refused:"))
    )


def render_failure_warning(degraded: Iterable[object]) -> str:
    """Render one stderr warning, or ``""`` when no guard failed."""
    failures = failure_markers(degraded)
    if not failures:
        return ""
    recovery = (
        " Run yoke sessions identity --json; repair the named registration cause and retry the hook."
        if any(marker.startswith("session_registration_refused:") for marker in failures)
        else ""
    )
    return format_hook_diagnostic(
        "hook runner", f"WARNING: {GUARD_FAILURE_MARKER}: {'; '.join(failures)}{recovery}\n"
    )


__all__ = [
    "FAILURE_PREFIX",
    "GUARD_FAILURE_MARKER",
    "failure_markers",
    "render_failure_warning",
]
