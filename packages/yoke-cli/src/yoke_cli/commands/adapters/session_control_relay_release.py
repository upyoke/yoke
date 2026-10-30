"""Build-source support for the standing machine-relay CLI.

An https relay follows the release its control plane serves; a local-universe
relay runs the machine's own installed Yoke, because that machine is also the
one serving the plane. Both shapes answer the same status and daemon calls.
The relay for the machine's active connection also moves the installed CLI to
each release it starts on.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal


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
        installer = importlib.import_module(
            "yoke_core.tools.session_relay_release_install"
        )
        recovery = installer.relay_release_recovery(instance.environment)
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
        "release_recovery": None if ready else local_install.local_launcher_recovery(),
    }


def release_status_is_healthy(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("release_current")) and not payload.get(
        "release_error_code"
    )


def serve_release_daemon(*, cycle_maintenance: Callable[[], None] | None = None) -> Any:
    """Run this relay's build: a pinned release, or the machine's own Yoke."""
    from yoke_harness.session_relay_daemon import serve_forever
    from yoke_harness.session_relay_harness_reconcile import (
        refresh_harness_inventory,
    )
    from yoke_harness.session_relay_inventory import collect_cached_inventory
    from yoke_harness.session_relay_process_restart import exec_relay_release

    from yoke_cli.config.session_relay_instance import (
        RelayInstanceError,
        door_relay_refusal,
        resolve_relay_instance,
    )

    release = importlib.import_module("yoke_core.tools.session_relay_release")
    release_install = importlib.import_module(
        "yoke_core.tools.session_relay_release_install"
    )
    instance = resolve_relay_instance()
    if refusal := door_relay_refusal(instance):
        raise RelayInstanceError(refusal)
    lane_sweep = importlib.import_module(
        "yoke_core.tools.session_relay_lane_sweep"
    ).relay_lane_sweep(instance)

    def maintain() -> None:
        # The host's own upkeep, then this machine's lane sweep when it is due.
        if cycle_maintenance is not None:
            cycle_maintenance()
        lane_sweep()

    if not instance.follows_served_release:
        # Nothing to follow: this machine serves the plane it polls, so the
        # running process is already the build the universe has. With no API
        # server, each cycle also runs the plane's upkeep.
        upkeep = importlib.import_module("yoke_core.domain.control_plane_upkeep")

        def maintain_local_universe() -> None:
            maintain()
            upkeep.run_control_plane_upkeep()

        return serve_forever(
            state_dir=instance.state_dir,
            inventory_provider=collect_cached_inventory,
            inventory_refresher=refresh_harness_inventory,
            cycle_maintenance=maintain_local_universe,
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
            compose_refusal(
                f"{detail}.",
                recovery=f"run `yoke --env {instance.environment} relay install`.",
            ),
        )

    def restart_from_pin(argv=None, *, executable=None):
        try:
            exec_relay_release(argv, executable=executable)
        except OSError as exc:
            raise release.RelayReleaseError(
                release.RELAY_RELEASE_START_FAILED,
                compose_refusal(
                    f"could not start the pinned relay release: {exc}.",
                    recovery=f"retry `yoke --env {instance.environment} relay install`.",
                ),
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

    if instance.machine_active:
        # This start is the relay observing its plane serving this release;
        # the installed CLI follows the active connection here, never on a
        # schedule.
        from yoke_cli.config.operator_cli_release_follow import follow_release

        follow_release(installed.pinned_release, instance.state_dir)

    def repin(served_build: str):
        return release_install.pin_relay_release(
            instance=instance,
            served_build=served_build,
        ).launch_executable

    return serve_forever(
        state_dir=instance.state_dir,
        inventory_provider=collect_cached_inventory,
        inventory_refresher=refresh_harness_inventory,
        cycle_maintenance=maintain,
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
