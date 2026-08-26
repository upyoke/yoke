"""Observed machine and harness-version facts for session registration."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.machine_config.runtime import ensure_machine_id


def client_executor_version(executor_surface: str | None) -> Optional[str]:
    """Return the version this session's own surface executable reports.

    Registration observes the surface rather than trusting anything the
    launcher put in the environment, so a session records the build it is
    actually running and agrees with every other reader of that surface.
    """
    from yoke_harness.session_relay_surface_probe_cache import (
        observed_surface_version,
    )

    return observed_surface_version(executor_surface)


def client_machine_id() -> Optional[str]:
    """Return the stable machine UUID, initializing configured machines."""
    try:
        return ensure_machine_id()
    except Exception:  # noqa: BLE001 - identity enrichment is best effort
        return None


__all__ = ["client_executor_version", "client_machine_id"]
