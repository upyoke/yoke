"""Native supervisor steps and completion teaching for relay onboarding."""

from __future__ import annotations

import sys
from yoke_cli.config.session_relay_instance import RELAY_LOGOUT_BEHAVIOR

RELAY_PLIST_TARGET = "~/Library/LaunchAgents/com.upyoke.relay[.<environment-id>].plist"
UNIT_INSTALL_ACTION = "install-session-relay-unit"
UNIT_ENABLE_ACTION = "enable-session-relay-user-service"
RELAY_UNIT_TARGET = "~/.config/systemd/user/com.upyoke.relay[.<environment-id>].service"


def lifecycle_steps() -> tuple[tuple[str, str], ...]:
    if sys.platform == "linux":
        return (
            (UNIT_INSTALL_ACTION, RELAY_UNIT_TARGET),
            (UNIT_ENABLE_ACTION, "systemd --user"),
        )
    return (
        ("install-session-relay-plist", RELAY_PLIST_TARGET),
        ("load-session-relay-login-item", "com.upyoke.relay"),
    )


def complete_lines() -> tuple[str, ...]:
    if sys.platform == "linux":
        return (
            f"Machine relay user unit: {RELAY_UNIT_TARGET}",
            "Machine relay starts at login and restarts on failure.",
            RELAY_LOGOUT_BEHAVIOR,
        )
    return (f"Machine relay plist: {RELAY_PLIST_TARGET}",)


def report_document(*, planned: bool) -> dict[str, str | None]:
    if sys.platform == "linux":
        return {"unit": RELAY_UNIT_TARGET if planned else None}
    return {"plist": RELAY_PLIST_TARGET if planned else None}
