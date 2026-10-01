"""Operator utility for the native machine relay in either build mode."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from yoke_cli.config.session_relay_instance import (
    RelayInstance,
    RelayInstanceError,
    resolve_relay_instance,
)
from yoke_core.tools.session_relay_plist import (
    RelayInstallError,
)
from yoke_core.tools.session_relay_systemd import RelaySystemdStatus
from yoke_core.tools.session_relay_plist import RelayLaunchdStatus
from yoke_core.tools.session_relay_service import (
    relay_service_operation,
    relay_service_current,
    relay_service_present,
)
from yoke_core.tools.session_relay_local_install import (
    local_launcher_path,
    local_launcher_ready,
)
from yoke_core.tools.session_relay_release import relay_release_status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_session_relay",
        description="Install, inspect, or uninstall the Yoke relay user service.",
    )
    parser.add_argument("action", choices=("install", "status", "uninstall"))
    parser.add_argument(
        "--environment",
        default=None,
        help=(
            "converge the relay of this configured environment instead of the "
            "machine's active one"
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        type=Path,
        help="read connections from this machine config instead of the default",
    )
    return parser


def _runnable(instance: RelayInstance, *, refresh_served: bool) -> bool:
    """Whether this relay's build source is present and current."""
    if instance.follows_served_release:
        release = relay_release_status(instance=instance, refresh_served=refresh_served)
        print(
            "session relay release: "
            f"pinned={release.pinned_release or 'missing'}, "
            f"served={release.served_build or 'unavailable'}, "
            f"current={'yes' if release.current else 'no'}"
        )
        if release.error_message:
            print(f"session relay release error: {release.error_message}")
        return release.current and not release.error_code
    # A local universe serves the build the relay already runs, so the
    # question is whether this machine's launcher is there to run.
    launcher = local_launcher_path()
    runnable = local_launcher_ready(launcher)
    print(
        "session relay build: local universe runs this machine's installed "
        f"Yoke at {launcher}, runnable={'yes' if runnable else 'no'}"
    )
    return runnable


def relay_is_satisfied(
    status: RelayLaunchdStatus | RelaySystemdStatus, *, runnable: bool
) -> bool:
    """Whether this exact relay needs no lifecycle write at all.

    Every fact a replacement would change is checked: the login item is
    loaded, the native service document matches the one this environment and config
    would write now, and the build source it points at is present and
    current. Anything short of that is an upgrade or a repair, never a skip.
    """
    return bool(
        status.supported
        and relay_service_current(status)
        and status.loaded
        and runnable
    )


def main(argv: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(argv)
    try:
        instance = resolve_relay_instance(
            config_path=parsed.config,
            environment=parsed.environment,
        )
    except RelayInstanceError as exc:
        print(f"session relay: {exc}", file=sys.stderr)
        return 1
    try:
        status = relay_service_operation(parsed.action, instance=instance)
    except RelayInstallError as exc:
        print(f"session relay: {exc}", file=sys.stderr)
        return 1
    print(
        "session relay: "
        f"env={status.environment or 'default'}, "
        f"service={'present' if relay_service_present(status) else 'missing'}, "
        f"loaded={'yes' if status.loaded else 'no'}, "
        f"current={'yes' if relay_service_current(status) else 'no'}"
    )
    if getattr(status, "reason", ""):
        print(f"session relay: {status.reason}", file=sys.stderr)
    runnable = _runnable(instance, refresh_served=parsed.action != "uninstall")
    if parsed.action == "uninstall":
        healthy = not relay_service_present(status) and not status.loaded
    else:
        healthy = relay_is_satisfied(status, runnable=runnable)
    return 0 if status.supported and healthy else 1


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())


__all__ = ["main", "relay_is_satisfied"]
