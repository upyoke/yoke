"""Read-only machine ownership inventory for full Yoke removal."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from yoke_cli.config import install_binding, local_universe_setup, machine_config
from yoke_cli.config.local_universe_connection import stored_dsn
from yoke_cli.config import machine_uninstall_detached
from yoke_cli.project_install.files import MANIFEST_REL
from yoke_cli.self_host import bundle, teardown
from yoke_contracts import owner_private_path
from yoke_contracts.machine_config import schema


# Native Windows hosts no self-host server: one Docker shows here runs in WSL2.
_NATIVE_WINDOWS = os.name == "nt"


class UninstallError(RuntimeError):
    """A named refusal with an actionable recovery."""


@dataclass(frozen=True)
class Inventory:
    home: Path
    config: Path
    projects: tuple[Path, ...]
    relay_envs: tuple[str, ...]
    local_universe: bool
    local_env: str | None
    bundles: tuple[tuple[Path, str | None], ...]
    discovery_error: str = ""
    # Seen from native Windows, a self-host server runs in WSL2 and is torn down there.
    wsl_bundles: tuple[str, ...] = ()

    @property
    def owns_data(self) -> bool:
        return self.local_universe or bool(self.bundles)


def inspect() -> Inventory:
    binding = install_binding.detect()
    if binding["kind"] == install_binding.KIND_SOURCE_CHECKOUT:
        raise UninstallError(
            "uninstall_source_checkout: this CLI runs from "
            f"{binding['checkout_root']}. Use your source-dev workflow to "
            "retire that checkout; run uninstall only from a packaged install."
        )
    home = machine_config.yoke_home().expanduser().absolute()
    config = machine_config.config_path().absolute()
    payload = machine_config.load_config(config)
    registered = machine_config.all_registered_checkouts(config)
    _assert_safe_home(home, registered)
    projects = tuple(p for p in registered if (p / MANIFEST_REL).is_file())
    connections = payload.get("connections") or {}
    if not isinstance(connections, dict):
        raise UninstallError(
            f"uninstall_config_invalid: connections in {config} must be an object. "
            "Repair the machine config and retry uninstall."
        )
    relay_envs = tuple(
        name
        for name, entry in connections.items()
        if isinstance(entry, dict)
        and (
            entry.get("transport") == schema.TRANSPORT_HTTPS
            or (
                entry.get("transport") in schema.POSTGRES_TRANSPORTS
                and not schema.connection_is_protected(entry)
            )
        )
    )
    local = local_universe_setup.local_cluster_initialized()
    local_env = None
    if local:
        engine = local_universe_setup._engine()
        expected = engine.local_dsn()
        local_env = next(
            (
                name
                for name, entry in connections.items()
                if isinstance(entry, dict)
                and not schema.connection_is_protected(entry)
                and entry.get("transport") in schema.POSTGRES_TRANSPORTS
                and stored_dsn(entry) == expected
            ),
            None,
        )
    directories, error = _self_host_directories()
    if error and not any(
        _is_loopback_url(entry.get("api_url"))
        for entry in connections.values()
        if isinstance(entry, dict)
    ):
        # Only a self-host server makes Docker relevant, and this machine
        # reaches its own server on loopback; without one, a stopped or broken
        # Docker cannot be hiding a Yoke install.
        error = ""
    wsl_bundles: tuple[str, ...] = ()
    if _NATIVE_WINDOWS:
        wsl_bundles, directories = directories, ()
    else:
        directories = _bundle_directories(directories)
    bundles = []
    for directory in directories:
        url = teardown.bundle_connect_url(directory)
        env = next(
            (
                name
                for name, entry in connections.items()
                if isinstance(entry, dict)
                and str(entry.get("api_url") or "").rstrip("/") == url
            ),
            None,
        )
        bundles.append((directory, env))
    return Inventory(
        home,
        config,
        projects,
        relay_envs,
        local,
        local_env,
        tuple(bundles),
        error,
        wsl_bundles,
    )


def _is_loopback_url(value: object) -> bool:
    host = urlsplit(str(value or "")).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _assert_safe_home(home: Path, checkouts: list[Path]) -> None:
    resolved = home.resolve()
    forbidden = (Path(resolved.anchor), Path.home().resolve(), *checkouts)
    if any(resolved == p or resolved in p.parents for p in forbidden):
        raise UninstallError(
            f"uninstall_unsafe_home: {home} contains a home or registered checkout. "
            "Correct YOKE_MACHINE_HOME to Yoke's dedicated directory before retrying."
        )
    if home.is_symlink():
        raise UninstallError(
            f"uninstall_home_symlink: {home} is a symlink. Set YOKE_MACHINE_HOME "
            "to the dedicated real directory before retrying."
        )
    try:
        machine_uninstall_detached.temp_root(home)
    except RuntimeError as exc:
        raise UninstallError(str(exc)) from None
    if home.exists():
        if not home.is_dir():
            raise UninstallError(
                f"uninstall_home_not_directory: {home}; repair the machine home before retrying."
            )
        if not owner_private_path.is_owner_controlled_directory(home):
            raise UninstallError(
                f"uninstall_home_permissions: {home} must be owned by you and "
                "writable by no other user. Repair its ownership and permissions "
                "before retrying."
            )


def _bundle_directories(listed: tuple[str, ...]) -> tuple[Path, ...]:
    directories = tuple(
        dict.fromkeys(Path(line).expanduser().resolve() for line in listed)
    )
    for directory in directories:
        if not (directory / bundle.COMPOSE_FILE_NAME).is_file():
            raise UninstallError(
                f"uninstall_bundle_missing: Docker owns a Yoke server at {directory}, "
                "but its Compose file is missing. Restore the bundle before uninstalling."
            )
    return directories


def _self_host_directories() -> tuple[tuple[str, ...], str]:
    """Bundle paths as Docker reports them, plus a discovery failure."""
    docker = shutil.which("docker")
    if not docker:
        return (), ""
    try:
        listed = subprocess.run(
            [
                docker,
                "ps",
                "-a",
                "--filter",
                "label=com.docker.compose.service=core",
                "--format",
                "{{.ID}}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if listed.returncode:
            return (
                (),
                "uninstall_docker_inventory_failed: start Docker and retry uninstall.",
            )
        ids = listed.stdout.split()
        if not ids:
            return (), ""
        # Print only the bundle path of a self-host server, never its environment secrets.
        template = (
            '{{range .Config.Env}}{{if eq . "YOKE_SERVER_MODE=self-host"}}'
            '{{index $.Config.Labels "com.docker.compose.project.working_dir"}}'
            "{{end}}{{end}}"
        )
        inspected = subprocess.run(
            [docker, "inspect", "--format", template, *ids],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if inspected.returncode:
            return (
                (),
                "uninstall_docker_inventory_failed: repair Docker inspection and retry.",
            )
        listed = (line.strip() for line in inspected.stdout.splitlines())
        return tuple(dict.fromkeys(line for line in listed if line)), ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (
            (),
            f"uninstall_docker_inventory_failed: {type(exc).__name__}; repair Docker and retry.",
        )
