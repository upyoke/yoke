"""Build-source support for the standing machine-relay CLI.

An https relay follows the release its control plane serves; a local-universe
relay runs the machine's own installed Yoke, because that machine is also the
one serving the plane. Both shapes answer the same status and daemon calls.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import importlib
from pathlib import Path
import sys
from typing import Any


def release_status_payload(
    launchd_status: object,
    *,
    refresh_served: bool,
) -> dict[str, Any]:
    """Render this relay's build source beside the launchd lifecycle state."""
    from yoke_cli.config.session_relay_instance import resolve_relay_instance

    release = importlib.import_module("yoke_core.tools.session_relay_release")

    environment = str(getattr(launchd_status, "environment", "") or "")
    instance = resolve_relay_instance(environment=environment or None)
    if not instance.follows_served_release:
        return _local_build_payload()
    status = release.relay_release_status(
        instance=instance,
        refresh_served=refresh_served,
    )
    recovery = ""
    if status.error_code:
        recovery = (
            f"verify `yoke --env {instance.environment} status`, then retry "
            f"`yoke --env {instance.environment} relay install`"
        )
    return {
        "pinned_release": status.pinned_release or None,
        "served_build": status.served_build or None,
        "release_current": status.current,
        "distribution_index": status.distribution_index or None,
        "release_error_code": status.error_code or None,
        "release_error": status.error_message or None,
        "release_recovery": recovery or None,
    }


def _local_build_payload() -> dict[str, Any]:
    """Report the installed launcher a local-universe relay runs.

    A local universe pins nothing and serves no wheel index, so those fields
    are absent rather than reported missing; readiness is whether the machine
    holds the launcher launchd was pointed at.
    """
    local_install = importlib.import_module(
        "yoke_core.tools.session_relay_local_install"
    )
    launcher = local_install.local_launcher_path()
    ready = local_install.local_launcher_ready(launcher)
    return {
        "pinned_release": None,
        "served_build": None,
        "release_current": ready,
        "distribution_index": None,
        "local_launcher": str(launcher),
        "release_error_code": None if ready else local_install.LOCAL_LAUNCHER_MISSING,
        "release_error": (
            None if ready else local_install.local_launcher_missing_message(launcher)
        ),
        "release_recovery": None if ready else local_install.LOCAL_LAUNCHER_RECOVERY,
    }


def release_status_is_healthy(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("release_current")) and not payload.get(
        "release_error_code"
    )


def serve_release_daemon(*, cycle_maintenance: Callable[[], None] | None = None) -> Any:
    """Run this relay's build: a pinned release, or the machine's own Yoke."""
    from yoke_cli.config.session_relay_instance import resolve_relay_instance
    from yoke_harness.session_relay_daemon import serve_forever
    from yoke_harness.session_relay_inventory import collect_cached_inventory
    from yoke_harness.session_relay_process_restart import exec_relay_release
    from yoke_harness.session_relay_surface_probe_cache import (
        refresh_surface_probe_cache,
    )

    release = importlib.import_module("yoke_core.tools.session_relay_release")
    release_install = importlib.import_module(
        "yoke_core.tools.session_relay_release_install"
    )
    instance = resolve_relay_instance()
    if not instance.follows_served_release:
        # Nothing to follow: this machine serves the plane it polls, so the
        # running process is already the build the universe has.
        return serve_forever(
            state_dir=instance.state_dir,
            inventory_provider=collect_cached_inventory,
            inventory_refresher=refresh_surface_probe_cache,
            cycle_maintenance=cycle_maintenance,
        )
    installed = release.relay_release_status(instance=instance, refresh_served=False)
    unconverged_launch = release.relay_launch_path(instance.state_dir)
    if (
        not installed.current
        and unconverged_launch.is_symlink()
        and not release.relay_launch_targets_runtime(instance.state_dir)
    ):
        installed = release_install.pin_relay_release(instance=instance)
    if not installed.current:
        code = str(installed.error_code or release.RELAY_RELEASE_INSTALL_FAILED)
        detail = str(
            installed.error_message
            or "the standing relay has no complete pinned release"
        )
        raise release.RelayReleaseError(
            code,
            f"{detail}. Recovery: run `yoke --env {instance.environment} "
            "relay install`.",
        )

    def restart_from_pin(argv=None, *, executable=None):
        try:
            exec_relay_release(argv, executable=executable)
        except OSError as exc:
            raise release.RelayReleaseError(
                release.RELAY_RELEASE_START_FAILED,
                "could not start the pinned relay "
                f"release: {exc}. Recovery: retry `yoke --env "
                f"{instance.environment} relay install`.",
            ) from exc
        raise release.RelayReleaseError(
            release.RELAY_RELEASE_START_FAILED,
            "pinned relay replacement returned without starting",
        )

    running_prefix = Path(sys.prefix).resolve()
    pinned_prefix = installed.runtime_python.parent.parent.resolve()
    if running_prefix != pinned_prefix:
        restart_from_pin(
            ["--env", instance.environment, "relay", "serve"],
            executable=installed.launch_executable,
        )

    def repin(served_build: str):
        return release_install.pin_relay_release(
            instance=instance,
            served_build=served_build,
        ).launch_executable

    return serve_forever(
        state_dir=instance.state_dir,
        inventory_provider=collect_cached_inventory,
        inventory_refresher=refresh_surface_probe_cache,
        cycle_maintenance=cycle_maintenance,
        pinned_release=installed.pinned_release,
        pin_served_release=repin,
        reload_argv=["--env", instance.environment, "relay", "serve"],
        reload_exec=restart_from_pin,
    )


__all__ = [
    "release_status_is_healthy",
    "release_status_payload",
    "serve_release_daemon",
]
