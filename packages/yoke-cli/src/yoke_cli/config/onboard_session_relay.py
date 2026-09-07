"""Explicit onboard plan and apply bridge for the macOS machine relay.

Every destination that can run a relay gets one, because the relay is what
makes a machine observable and drivable: it registers the harnesses this
machine can actually start, reports session liveness, and executes launch and
resume work. Leaving it out of one destination would make that destination's
install quietly incapable of the operations the product offers everywhere else.

The two destinations differ only in where the relay's build comes from -- an
https plane serves a release the relay pins, while a local universe is served
by the machine the relay runs on, so it runs that machine's installed Yoke.
That difference is owned by the relay installer; onboarding names it in the
plan and the completion summary so the operator sees which one applied.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Callable, Mapping


RELAY_PLIST_TARGET = "~/Library/LaunchAgents/com.upyoke.relay[.<environment-id>].plist"
RELAY_INSTALL_TIMEOUT_SECONDS = 300
#: Steps every relay install performs, whichever build source it runs.
RELAY_LIFECYCLE_STEPS = (
    ("install-session-relay-plist", RELAY_PLIST_TARGET),
    ("load-session-relay-login-item", "com.upyoke.relay"),
)
#: The build-source step, one per destination.
RELAY_SERVED_RELEASE_STEP = ("reuse-session-relay-token", "existing-api-token")
RELAY_LOCAL_BUILD_STEP = (
    "run-session-relay-on-installed-yoke",
    "this machine's installed Yoke",
)

_SHARED_COMPLETE_LINES = (f"Machine relay plist: {RELAY_PLIST_TARGET}",)
_SERVED_RELEASE_COMPLETE_LINES = (
    "Machine relay runs the release served by its selected environment.",
    "Machine relay uses one stable relay-owned Python with isolated release packages.",
    "Machine relay reuses your existing Yoke API token.",
)
_LOCAL_BUILD_COMPLETE_LINES = (
    "Machine relay runs this machine's installed Yoke, which also serves your "
    "local universe.",
    "Machine relay reaches that universe through your machine config, with no "
    "account or API token.",
)


class OnboardSessionRelayError(RuntimeError):
    """The explicit relay step could not install its login item."""


def is_supported(
    *,
    local_destination: bool,
    platform: str | None = None,
) -> bool:
    """Whether this machine can run a relay for the chosen destination."""
    resolved_platform = sys.platform if platform is None else platform
    # launchd is the only supervisor the relay installs into today; the
    # destination no longer decides, because both destinations need a relay.
    del local_destination
    return resolved_platform == "darwin"


def plan_steps(*, local_destination: bool) -> list[dict[str, str]]:
    if not is_supported(local_destination=local_destination):
        return []
    build_step = RELAY_LOCAL_BUILD_STEP if local_destination else RELAY_SERVED_RELEASE_STEP
    return [
        {"action": action, "target": target}
        for action, target in (*RELAY_LIFECYCLE_STEPS, build_step)
    ]


def progress_steps(*, local_destination: bool) -> tuple[tuple[str, str], ...]:
    """The same steps as ``plan_steps``, shaped for the progress emitter."""
    return tuple(
        (step["action"], step["target"])
        for step in plan_steps(local_destination=local_destination)
    )


def setup_complete_lines(*, local_destination: bool) -> tuple[str, ...]:
    """What the Setup-complete screen tells the operator about their relay."""
    build_lines = (
        _LOCAL_BUILD_COMPLETE_LINES
        if local_destination
        else _SERVED_RELEASE_COMPLETE_LINES
    )
    return (*_SHARED_COMPLETE_LINES, *build_lines)


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
            timeout=RELAY_INSTALL_TIMEOUT_SECONDS,
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


def report_fragment(
    *, planned: bool, installed: bool, local_destination: bool = False
) -> dict[str, Any]:
    return {
        "planned": planned,
        "installed": installed,
        "plist": RELAY_PLIST_TARGET if planned else None,
        "local_build": local_destination,
    }


def report_complete_lines(fragment: Any) -> tuple[str, ...]:
    """Completion lines for an applied report, or none when nothing installed."""
    if not isinstance(fragment, Mapping) or not fragment.get("installed"):
        return ()
    return setup_complete_lines(
        local_destination=bool(fragment.get("local_build")),
    )


__all__ = [
    "OnboardSessionRelayError",
    "RELAY_INSTALL_TIMEOUT_SECONDS",
    "RELAY_LIFECYCLE_STEPS",
    "RELAY_LOCAL_BUILD_STEP",
    "RELAY_PLIST_TARGET",
    "RELAY_SERVED_RELEASE_STEP",
    "install",
    "is_supported",
    "plan_steps",
    "progress_steps",
    "report_complete_lines",
    "report_fragment",
    "setup_complete_lines",
]
