"""Release-pin support for the standing machine-relay CLI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any


def release_status_payload(
    launchd_status: object,
    *,
    refresh_served: bool,
) -> dict[str, Any]:
    """Render the venv pin beside the launchd lifecycle state."""
    from yoke_cli.config.session_relay_instance import resolve_relay_instance
    from yoke_core.tools.session_relay_release import relay_release_status

    environment = str(getattr(launchd_status, "environment", "") or "")
    instance = resolve_relay_instance(environment=environment or None)
    status = relay_release_status(
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


def release_status_is_healthy(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("release_current")) and not payload.get(
        "release_error_code"
    )


def serve_release_daemon() -> Any:
    """Run and re-pin the daemon from its environment-owned venv."""
    from yoke_cli.config.session_relay_instance import resolve_relay_instance
    from yoke_core.tools.session_relay_release import (
        RELAY_RELEASE_INSTALL_FAILED,
        RELAY_RELEASE_START_FAILED,
        RelayReleaseError,
        relay_release_status,
    )
    from yoke_core.tools.session_relay_release_install import pin_relay_release
    from yoke_harness.session_relay_daemon import serve_forever
    from yoke_harness.session_relay_inventory import collect_cached_inventory
    from yoke_harness.session_relay_process_restart import exec_relay_release
    from yoke_harness.session_relay_surface_probe_cache import (
        refresh_surface_probe_cache,
    )

    instance = resolve_relay_instance()
    installed = relay_release_status(instance=instance, refresh_served=False)
    if not installed.current:
        code = str(installed.error_code or RELAY_RELEASE_INSTALL_FAILED)
        detail = str(
            installed.error_message
            or "the standing relay has no complete pinned release"
        )
        raise RelayReleaseError(
            code,
            f"{detail}. Recovery: run `yoke --env {instance.environment} "
            "relay install`.",
        )
    running_prefix = Path(sys.prefix).resolve()
    pinned_prefix = installed.python.parent.parent.resolve()
    if running_prefix != pinned_prefix:
        try:
            exec_relay_release(
                ["--env", instance.environment, "relay", "serve"],
                executable=installed.executable,
            )
        except OSError as exc:
            raise RelayReleaseError(
                RELAY_RELEASE_START_FAILED,
                "could not start the pinned relay "
                f"release: {exc}. Recovery: retry `yoke --env "
                f"{instance.environment} relay install`.",
            ) from exc
        raise RelayReleaseError(
            RELAY_RELEASE_START_FAILED,
            "pinned relay replacement returned without starting",
        )

    def repin(served_build: str):
        return pin_relay_release(
            instance=instance,
            served_build=served_build,
        ).executable

    return serve_forever(
        state_dir=instance.state_dir,
        inventory_provider=collect_cached_inventory,
        inventory_refresher=refresh_surface_probe_cache,
        pinned_release=installed.pinned_release,
        pin_served_release=repin,
        reload_argv=["--env", instance.environment, "relay", "serve"],
    )


__all__ = [
    "release_status_is_healthy",
    "release_status_payload",
    "serve_release_daemon",
]
