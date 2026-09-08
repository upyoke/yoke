"""Operator utility for the macOS machine relay in either build mode."""

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
    RelayLaunchdStatus,
    install_relay_launchd,
    relay_launchd_status,
    uninstall_relay_launchd,
)
from yoke_core.tools.session_relay_local_install import (
    local_launcher_path,
    local_launcher_ready,
)
from yoke_core.tools.session_relay_release import relay_release_status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_session_relay",
        description="Install, inspect, or uninstall the macOS Yoke relay launch agent.",
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


def relay_is_satisfied(status: RelayLaunchdStatus, *, runnable: bool) -> bool:
    """Whether this exact relay needs no lifecycle write at all.

    Every fact a replacement would change is checked: the login item is
    loaded, the launchd document matches the one this environment and config
    would write now, and the build source it points at is present and
    current. Anything short of that is an upgrade or a repair, never a skip.
    """
    return bool(
        status.supported
        and status.plist_present
        and status.loaded
        and status.plist_current
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
        if parsed.action == "install":
            status = install_relay_launchd(instance=instance)
        elif parsed.action == "uninstall":
            status = uninstall_relay_launchd(instance=instance)
        else:
            status = relay_launchd_status(instance=instance)
    except RelayInstallError as exc:
        print(f"session relay: {exc}", file=sys.stderr)
        return 1
    print(
        "session relay: "
        f"env={status.environment or 'default'}, "
        f"plist={'present' if status.plist_present else 'missing'}, "
        f"loaded={'yes' if status.loaded else 'no'}, "
        f"current={'yes' if status.plist_current else 'no'}"
    )
    runnable = _runnable(instance, refresh_served=parsed.action != "uninstall")
    if parsed.action == "uninstall":
        healthy = not status.plist_present and not status.loaded
    else:
        healthy = relay_is_satisfied(status, runnable=runnable)
    return 0 if status.supported and healthy else 1


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())


__all__ = ["main", "relay_is_satisfied"]
