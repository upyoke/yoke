"""Native supervisor steps and completion teaching for relay onboarding."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Mapping

from yoke_contracts.machine_config.relay_instance import (
    RELAY_LOGOUT_BEHAVIOR,
    WINDOWS_RELAY_LOGOUT_BEHAVIOR,
    relay_instance_label,
)

UNIT_INSTALL_ACTION = "install-session-relay-unit"
UNIT_ENABLE_ACTION = "enable-session-relay-user-service"


def lifecycle_steps(
    *, config_path: str | Path, environment: str
) -> tuple[tuple[str, str], ...]:
    label = relay_instance_label(
        config_path=config_path,
        environment=environment,
    )
    if sys.platform == "linux":
        return (
            (UNIT_INSTALL_ACTION, f"~/.config/systemd/user/{label}.service"),
            (UNIT_ENABLE_ACTION, "systemd --user"),
        )
    if sys.platform == "win32":
        return (
            ("install-session-relay-task", label),
            ("run-session-relay-task", "Task Scheduler"),
        )
    return (
        ("install-session-relay-plist", f"~/Library/LaunchAgents/{label}.plist"),
        ("load-session-relay-login-item", label),
    )


def complete_lines(document: Mapping[str, object]) -> tuple[str, ...]:
    if document.get("task"):
        return (
            f"Machine relay scheduled task: {document['task']}",
            "Machine relay starts at login and runs on battery power.",
            WINDOWS_RELAY_LOGOUT_BEHAVIOR,
        )
    if document.get("unit"):
        return (
            f"Machine relay user unit: {document['unit']}",
            "Machine relay starts at login and restarts on failure.",
            RELAY_LOGOUT_BEHAVIOR,
        )
    return (
        (f"Machine relay plist: {document['plist']}",) if document.get("plist") else ()
    )


def report_document(
    *, planned: bool, config_path: str | Path, environment: str
) -> dict[str, str | None]:
    key = {"linux": "unit", "win32": "task"}.get(sys.platform, "plist")
    target = (
        lifecycle_steps(config_path=config_path, environment=environment)[0][1]
        if planned
        else None
    )
    return {key: target}
