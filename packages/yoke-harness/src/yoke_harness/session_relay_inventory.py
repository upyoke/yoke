"""Public machine facts attached to each relay heartbeat."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from yoke_cli.config import machine_config
from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.machine_config.machine_capacity import observe_machine_capacity
from yoke_contracts.machine_config.machine_name import machine_display_name
from yoke_contracts.machine_config.runtime import ensure_machine_id, read_settings
from yoke_harness.session_relay_plan_limits import observe_plan_limits
from yoke_harness.session_relay_surface_probe_cache import (
    cached_surface_versions,
)
from yoke_harness.session_relay_surface_probes import (
    APP_SURFACE_PROBES,
    CLI_SURFACE_PROBES,
    ResolvedNativeCli,
    probe_app_surface,
    probe_cli_surface,
    resolve_native_cli,
    resolve_native_cli_source,
)


@dataclass(frozen=True)
class RelayInventory:
    relay_id: str
    machine_id: str
    hostname: str
    relay_version: str
    project_ids: tuple[int, ...]
    surface_versions: dict[str, str]
    surface_plan_limits: dict[str, dict[str, object]] = field(default_factory=dict)
    machine_capacity: dict[str, object] = field(default_factory=dict)

    def claim_payload(
        self,
        *,
        wait_seconds: int | None = None,
        broker_only: bool = False,
        broker_lease_id: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "relay_id": self.relay_id,
            "machine_id": self.machine_id,
            "hostname": self.hostname,
            "relay_version": self.relay_version,
            "projects": list(self.project_ids),
            "surfaces": dict(self.surface_versions),
            "plan_limits": dict(self.surface_plan_limits),
            "capacity": dict(self.machine_capacity),
        }
        if wait_seconds is not None:
            payload["wait_seconds"] = wait_seconds
        if broker_only:
            payload["broker_only"] = True
        if broker_lease_id:
            payload["broker_lease_id"] = broker_lease_id
        return payload


def probe_cli_version(command: tuple[str, ...]) -> str | None:
    result = probe_cli_surface("cli", command)
    return result.version if result.verdict == "ok" else None


def probe_app_version(path: Path) -> str | None:
    result = probe_app_surface("app", path)
    return result.version if result.verdict == "ok" else None


def probe_surface_version(surface: str) -> str | None:
    """Return one locally observed surface version without full inventory."""
    if surface in CLI_SURFACE_PROBES:
        return probe_cli_version(CLI_SURFACE_PROBES[surface])
    if surface in APP_SURFACE_PROBES:
        return probe_app_version(APP_SURFACE_PROBES[surface])
    return None


def _inventory(
    versions: dict[str, str],
    plan_limits: dict[str, dict[str, object]] | None = None,
) -> RelayInventory:
    project_ids = tuple(
        sorted(
            {
                project.project_id
                for project in machine_config.configured_projects(existing_only=True)
            }
        )
    )
    machine_id = ensure_machine_id()
    # Measured on every poll: the reading is what lets the launch plane refuse
    # to place a worker on a box that has no room for one.
    capacity = observe_machine_capacity(
        read_settings(),
        observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return RelayInventory(
        relay_id=f"machine:{machine_id}",
        machine_id=machine_id,
        hostname=machine_display_name(),
        relay_version=local_handshake_version() or "source",
        project_ids=project_ids,
        surface_versions=versions,
        surface_plan_limits=dict(plan_limits or {}),
        machine_capacity=capacity.to_dict(),
    )


def collect_inventory(
    *,
    cli_probe: Callable[[tuple[str, ...]], str | None] = probe_cli_version,
    app_probe: Callable[[Path], str | None] = probe_app_version,
) -> RelayInventory:
    versions: dict[str, str] = {}
    for surface, command in CLI_SURFACE_PROBES.items():
        version = cli_probe(command)
        if version:
            versions[surface] = version
    for surface, path in APP_SURFACE_PROBES.items():
        version = app_probe(path)
        if version:
            versions[surface] = version
    return _inventory(versions, observe_plan_limits(tuple(versions)))


def collect_cached_inventory(*, state_dir: Path | None = None) -> RelayInventory:
    """Return cache-backed versions without running a live probe inline."""
    versions = cached_surface_versions(state_dir=state_dir)
    return _inventory(
        versions, observe_plan_limits(tuple(versions), state_dir=state_dir)
    )


__all__ = [
    "RelayInventory",
    "ResolvedNativeCli",
    "collect_cached_inventory",
    "collect_inventory",
    "probe_app_version",
    "probe_cli_version",
    "resolve_native_cli",
    "resolve_native_cli_source",
    "probe_surface_version",
]
