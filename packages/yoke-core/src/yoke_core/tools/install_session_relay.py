"""Operator utility for the macOS one-shot machine-relay login item."""

from __future__ import annotations

import argparse
from typing import Sequence

from yoke_core.tools.session_relay_plist import (
    RelayInstallError,
    install_relay_launchd,
    relay_launchd_status,
    uninstall_relay_launchd,
)
from yoke_core.tools.session_relay_release import relay_release_status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_session_relay",
        description="Install, inspect, or uninstall the macOS Yoke relay login item.",
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
    release = relay_release_status(refresh_served=parsed.action != "uninstall")
    print(
        "session relay release: "
        f"pinned={release.pinned_release or 'missing'}, "
        f"served={release.served_build or 'unavailable'}, "
        f"current={'yes' if release.current else 'no'}"
    )
    if parsed.action == "uninstall":
        healthy = not status.plist_present and not status.loaded
    else:
        healthy = (
            status.plist_present
            and status.loaded
            and status.plist_current
            and release.current
            and not release.error_code
        )
    return 0 if status.supported and healthy else 1


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())


__all__ = ["main"]
