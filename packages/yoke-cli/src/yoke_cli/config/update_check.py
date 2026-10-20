"""Client-local logic behind ``yoke update --check``.

Reports which side of this machine's Yoke is behind its release channel:
the installed CLI, the server engine of the active connection, or neither.
Shipped level defaults and the model catalog live in the server engine, so
the answer also says who can bring them current:

- ``local``: the embedded local universe runs this machine's own engine;
  ``yoke update`` updates the CLI and the local server together.
- ``server``: a self-hosted team server; ``yoke update`` updates only this
  CLI, and the server admin upgrades the server.
- ``hosted``: upyoke.com; releases deploy to hosted servers, so the engine
  arrives with the hosted release.

It also proves the installed build: the CLI wheel's full source commit must
equal the commit its release manifest names, and the release's published
wheel sha256 values are reported (:mod:`release_build`).

The channel's latest release comes from :func:`self_update.resolve_target`;
the server engine version comes from the manifest response header the active
HTTPS env already serves. No server function is involved.
"""

from __future__ import annotations

from typing import Any

from yoke_cli import manifest
from yoke_cli.config import (
    install_binding,
    machine_config,
    release_build,
    self_update,
)
from yoke_cli.config.onboard_destinations import destination_for_api_url
from yoke_contracts.deployment_destination import (
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
)
from yoke_contracts.engine_version import (
    compare_engine_versions,
    installed_engine_version,
)
from yoke_contracts.machine_config.schema_transport import TRANSPORT_HTTPS

BEHIND_CLI = "cli"
BEHIND_SERVER = "server"
BEHIND_NONE = "none"

_NEXT_STEP = {
    (BEHIND_CLI, DESTINATION_LOCAL): (
        "Run `yoke update`; it updates this CLI and the local server together."
    ),
    (BEHIND_CLI, DESTINATION_SERVER): (
        "Run `yoke update` for this CLI, then ask the server admin to upgrade "
        "the team server if it is behind too."
    ),
    (BEHIND_CLI, DESTINATION_HOSTED): (
        "Run `yoke update` for this CLI; the hosted server updates with each "
        "hosted release."
    ),
    (BEHIND_SERVER, DESTINATION_LOCAL): (
        "Run `yoke update`; it updates this CLI and the local server together."
    ),
    (BEHIND_SERVER, DESTINATION_SERVER): (
        "Ask the server admin to upgrade the team server to the channel's "
        "latest release; `yoke update` updates only this CLI."
    ),
    (BEHIND_SERVER, DESTINATION_HOSTED): (
        "The hosted server is still rolling out this release; new defaults "
        "arrive with the hosted release, and nothing on this machine needs to run."
    ),
}


def run_check(*, channel: str | None = None) -> dict[str, Any]:
    """Prove the installed build, then compare it and the server to the latest."""
    try:
        binding = install_binding.require_packaged_install("yoke update --check")
    except install_binding.SourceCheckoutError as exc:
        raise self_update.SelfUpdateError(str(exc)) from exc
    cli_version = str(binding["version"] or "").strip()
    if not cli_version:
        raise self_update.SelfUpdateError(
            "could not determine the installed Yoke version; repair with "
            "the public installer (curl -fsSL https://upyoke.com/install | "
            "sh) before running `yoke update --check`"
        )
    target = self_update.resolve_target(channel=channel)
    try:
        wheels = release_build.verify_installed(
            version=cli_version,
            source_commit=binding["source_commit"],
            base_url=target.base_url,
        )
    except release_build.ReleaseBuildError as exc:
        raise self_update.SelfUpdateError(str(exc)) from exc
    env_name, destination, server_version = _server_engine(cli_version)
    behind = _behind(cli_version, server_version, target.version)
    return {
        "channel": target.channel,
        "latest_version": target.version,
        "cli_version": cli_version,
        "source_commit": binding["source_commit"],
        "wheels": wheels,
        "env": env_name,
        "destination": destination,
        "server_engine_version": server_version,
        "behind": behind,
        "next_step": _NEXT_STEP.get((behind, destination), ""),
    }


def _server_engine(cli_version: str) -> tuple[str, str, str]:
    """``(env, destination, engine version)`` of the active connection."""
    try:
        connection = machine_config.active_connection()
    except (
        machine_config.MachineConfigError,
        machine_config.contract.MachineConfigContractError,
    ) as exc:
        raise self_update.SelfUpdateError(
            f"active_connection_unavailable: {exc}. Pick a connection with "
            "`yoke env use <env>` (list them with `yoke env list`), then rerun "
            "`yoke update --check`."
        ) from exc
    env_name = str(connection.get("env") or "")
    if str(connection.get("transport") or "") != TRANSPORT_HTTPS:
        # The local universe runs this process's own engine.
        return env_name, DESTINATION_LOCAL, installed_engine_version() or cli_version
    destination = destination_for_api_url(connection.get("api_url"))
    served = manifest.fetch_env_manifest(env_name) or {}
    server_version = str(served.get("server_engine_version") or "").strip()
    if not server_version:
        reason = manifest.diagnose_env_manifest_fetch(env_name) or (
            "the server did not advertise its engine version"
        )
        raise self_update.SelfUpdateError(
            f"server_version_unavailable: could not read the engine version "
            f"of env {env_name!r} ({reason}). Check that env's api_url and "
            "sign-in with `yoke env list`, then rerun `yoke update --check`."
        )
    return env_name, destination, server_version


def _behind(cli_version: str, server_version: str, latest: str) -> str:
    if _older(cli_version, latest):
        return BEHIND_CLI
    if _older(server_version, latest):
        return BEHIND_SERVER
    return BEHIND_NONE


def _older(version: str, latest: str) -> bool:
    return compare_engine_versions(version, latest) == -1


__all__ = ["BEHIND_CLI", "BEHIND_NONE", "BEHIND_SERVER", "run_check"]
