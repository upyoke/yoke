"""Operator utility for the macOS machine relay in either build mode."""

from __future__ import annotations

import argparse
from typing import Sequence

from yoke_core.tools.session_relay_plist import (
    RelayInstallError,
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(argv)
    try:
        if parsed.action == "install":
            status = install_relay_launchd()
        elif parsed.action == "uninstall":
            status = uninstall_relay_launchd()
        else:
            status = relay_launchd_status()
    except RelayInstallError as exc:
        print(f"session relay: {exc}")
        return 1
    print(
        "session relay: "
        f"plist={'present' if status.plist_present else 'missing'}, "
        f"loaded={'yes' if status.loaded else 'no'}, "
        f"current={'yes' if status.plist_current else 'no'}"
    )
    if status.follows_served_release:
        release = relay_release_status(refresh_served=parsed.action != "uninstall")
        print(
            "session relay release: "
            f"pinned={release.pinned_release or 'missing'}, "
            f"served={release.served_build or 'unavailable'}, "
            f"current={'yes' if release.current else 'no'}"
        )
        runnable = release.current and not release.error_code
    else:
        # A local universe serves the build the relay already runs, so the
        # question is whether this machine's launcher is there to run.
        launcher = local_launcher_path()
        runnable = local_launcher_ready(launcher)
        print(
            "session relay build: local universe runs this machine's installed "
            f"Yoke at {launcher}, runnable={'yes' if runnable else 'no'}"
        )
    if parsed.action == "uninstall":
        healthy = not status.plist_present and not status.loaded
    else:
        healthy = (
            status.plist_present
            and status.loaded
            and status.plist_current
            and runnable
        )
    return 0 if status.supported and healthy else 1


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())


__all__ = ["main"]
