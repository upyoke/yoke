"""Observed machine and harness-version facts for session registration."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.machine_config.runtime import ensure_machine_id


def client_executor_version(
    executor: str | None,
    executor_surface: str | None,
) -> Optional[str]:
    """Return the version this session's own surface executable reports.

    Registration observes the surface rather than trusting anything the
    launcher put in the environment, so a session records the build it is
    actually running and agrees with every other reader of that surface.

    A harness names its surface in its own family-relative vocabulary —
    Claude Code exports ``CLAUDE_CODE_ENTRYPOINT=cli`` — while the shared
    probe cache every other reader consults is keyed on the family-qualified
    surface (``claude-cli``). Composing the two here is what puts this reader
    on that shared key; observing the raw token instead finds no surface at
    all and records an unknown version for a surface the machine can see.
    """
    from yoke_harness.hooks.identity_runtime import compose_executor_from_entrypoint
    from yoke_harness.session_relay_surface_probe_cache import (
        observed_surface_version,
    )

    surface = str(executor_surface or "").strip()
    if executor and surface:
        surface = compose_executor_from_entrypoint(executor, surface)
    return observed_surface_version(surface)


def client_machine_id() -> Optional[str]:
    """Return the stable machine UUID, initializing configured machines."""
    try:
        return ensure_machine_id()
    except Exception:  # noqa: BLE001 - identity enrichment is best effort
        return None


__all__ = ["client_executor_version", "client_machine_id"]
