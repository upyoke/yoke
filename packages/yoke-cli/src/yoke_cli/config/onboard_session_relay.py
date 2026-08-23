"""Explicit onboard plan and apply bridge for the macOS machine relay."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Callable


RELAY_PLIST_TARGET = "~/Library/LaunchAgents/com.upyoke.relay[.<environment-id>].plist"
RELAY_PLAN_STEPS = (
    ("install-session-relay-plist", RELAY_PLIST_TARGET),
    ("load-session-relay-login-item", "com.upyoke.relay"),
    ("reuse-session-relay-token", "existing-api-token"),
)
RELAY_SETUP_COMPLETE_LINES = (
    f"Machine relay plist: {RELAY_PLIST_TARGET}",
    "Machine relay runs as an environment-pinned login item.",
    "Machine relay reuses your existing Yoke API token.",
)


class OnboardSessionRelayError(RuntimeError):
    """The explicit relay step could not install its login item."""


def is_supported(
    *,
    local_destination: bool,
    platform: str | None = None,
) -> bool:
    resolved_platform = sys.platform if platform is None else platform
    return resolved_platform == "darwin" and not local_destination


def plan_steps(*, local_destination: bool) -> list[dict[str, str]]:
    if not is_supported(local_destination=local_destination):
        return []
    return [{"action": action, "target": target} for action, target in RELAY_PLAN_STEPS]


def install(
    *,
    local_destination: bool,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    if not is_supported(local_destination=local_destination):
        return False
    try:
        completed = runner(
            [
                sys.executable,
                "-m",
                "yoke_core.tools.install_session_relay",
                "install",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OnboardSessionRelayError(
            "the machine relay installer could not start"
        ) from exc
    if completed.returncode != 0:
        raise OnboardSessionRelayError(
            "the machine relay login item could not be installed; "
            "run `yoke relay install` for status"
        )
    return True


def report_fragment(*, planned: bool, installed: bool) -> dict[str, Any]:
    return {
        "planned": planned,
        "installed": installed,
        "plist": RELAY_PLIST_TARGET if planned else None,
    }


__all__ = [
    "OnboardSessionRelayError",
    "RELAY_PLAN_STEPS",
    "RELAY_PLIST_TARGET",
    "RELAY_SETUP_COMPLETE_LINES",
    "install",
    "is_supported",
    "plan_steps",
    "report_fragment",
]
