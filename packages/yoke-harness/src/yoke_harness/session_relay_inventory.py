"""Public machine facts attached to each relay heartbeat."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import subprocess
from typing import Callable

from yoke_cli.config import machine_config
from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.machine_config.runtime import ensure_machine_id


_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)+(?:[-+._A-Za-z0-9]*)?")
_CLI_PROBES = {
    "claude-cli": ("claude", "--version"),
    "codex-cli": ("codex", "--version"),
    "cursor-cli": ("cursor-agent", "--version"),
}
_APP_PROBES = {
    "claude-desktop": Path("/Applications/Claude.app/Contents/Info.plist"),
    "codex-desktop": Path("/Applications/ChatGPT.app/Contents/Info.plist"),
    "cursor-desktop": Path("/Applications/Cursor.app/Contents/Info.plist"),
}
_CLI_FALLBACKS = {
    "codex": _APP_PROBES["codex-desktop"].parent / "Resources" / "codex",
}


@dataclass(frozen=True)
class RelayInventory:
    relay_id: str
    machine_id: str
    hostname: str
    relay_version: str
    project_ids: tuple[int, ...]
    surface_versions: dict[str, str]

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
        }
        if wait_seconds is not None:
            payload["wait_seconds"] = wait_seconds
        if broker_only:
            payload["broker_only"] = True
        if broker_lease_id:
            payload["broker_lease_id"] = broker_lease_id
        return payload


def _version_token(text: str) -> str | None:
    matched = _VERSION_PATTERN.search(text)
    return matched.group(0).rstrip("-+._") if matched else None


def _resolve_cli(command_name: str) -> str | None:
    found = shutil.which(command_name)
    if found:
        return found
    fallback = _CLI_FALLBACKS.get(command_name)
    if (
        fallback is not None
        and fallback.is_file()
        and os.access(fallback, os.X_OK)
    ):
        return str(fallback)
    return None


def probe_cli_version(command: tuple[str, ...]) -> str | None:
    executable = _resolve_cli(command[0])
    if not executable:
        return None
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return _version_token((completed.stdout or completed.stderr or "").strip())


def probe_app_version(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    value = str(payload.get("CFBundleShortVersionString") or "").strip()
    return _version_token(value)


def probe_surface_version(surface: str) -> str | None:
    """Return one locally observed surface version without full inventory."""
    if surface in _APP_PROBES:
        return probe_app_version(_APP_PROBES[surface])
    if surface in _CLI_PROBES:
        return probe_cli_version(_CLI_PROBES[surface])
    return None


def collect_inventory(
    *,
    cli_probe: Callable[[tuple[str, ...]], str | None] = probe_cli_version,
    app_probe: Callable[[Path], str | None] = probe_app_version,
) -> RelayInventory:
    machine_id = ensure_machine_id()
    versions: dict[str, str] = {}
    for surface, command in _CLI_PROBES.items():
        version = cli_probe(command)
        if version:
            versions[surface] = version
    for surface, path in _APP_PROBES.items():
        version = app_probe(path)
        if version:
            versions[surface] = version
    project_ids = tuple(
        sorted(
            {
                project.project_id
                for project in machine_config.configured_projects(existing_only=True)
            }
        )
    )
    return RelayInventory(
        relay_id=f"machine:{machine_id}",
        machine_id=machine_id,
        hostname=socket.gethostname(),
        relay_version=local_handshake_version() or "source",
        project_ids=project_ids,
        surface_versions=versions,
    )


__all__ = [
    "RelayInventory",
    "collect_inventory",
    "probe_app_version",
    "probe_cli_version",
    "probe_surface_version",
]
