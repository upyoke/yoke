"""How long setup waits on the machine relay, and what it says while it waits.

The install backstop covers the runtime and release environments, the bounded
dependency install, package verification, service setup, and any wait for a
daemon pin already in progress. Setup separately waits for the relay's first
heartbeat and reports a heartbeat that has not arrived as pending.
"""

from __future__ import annotations

import importlib
import re
import subprocess
from typing import Callable

from yoke_cli.config.onboard_apply_report_metadata import sanitize_text
from yoke_contracts.designed_wait import announce_designed_wait, poll_every


#: Whole-installer backstop, outside the dependency and verification bounds.
RELAY_INSTALL_TIMEOUT_SECONDS = 900
#: Reading status inspects the user service and shakes hands with the plane.
RELAY_STATUS_TIMEOUT_SECONDS = 60
#: Covers the relay pinning a release and restarting before its first heartbeat;
#: a native Windows cold start first connected 116 s after its process started.
RELAY_CONNECT_WAIT_SECONDS = 300
#: How often the heartbeat wait reads the relay's connection.
RELAY_CONNECT_POLL_SECONDS = 1.0
#: The ``install_health`` check a pending heartbeat stands in for.
RELAY_HEALTH_CHECK = "session-relay"

WaitForConnection = Callable[[float], bool]


_INSTALL_TIMING = re.compile(
    r"relay install: (?:runtime|release venv|dependencies|verify) took [0-9]+\.[0-9]{2} s"
)


def install_timing_lines(stderr: str | bytes | None) -> tuple[str, ...]:
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    return tuple(
        line for line in (stderr or "").splitlines() if _INSTALL_TIMING.fullmatch(line)
    )


def install_timeout_message(exc: subprocess.TimeoutExpired, *, recovery: str) -> str:
    timings = install_timing_lines(exc.stderr)
    detail = f" Last completed step: {timings[-1]}." if timings else ""
    notes = " ".join(getattr(exc, "__notes__", ()))
    if notes:
        detail += f" {sanitize_text(notes)}."
    return (
        f"the machine relay installer did not finish within "
        f"{RELAY_INSTALL_TIMEOUT_SECONDS} seconds.{detail} {recovery}"
    )


def announce_install(write: Callable[[str], None] | None = None) -> str:
    return announce_designed_wait(
        "the machine relay installer (a first release install builds its "
        "Python environment)",
        max_wait_seconds=RELAY_INSTALL_TIMEOUT_SECONDS,
        write=write,
    )


def announce_connection(write: Callable[[str], None] | None = None) -> str:
    return announce_designed_wait(
        "the machine relay's first heartbeat",
        max_wait_seconds=RELAY_CONNECT_WAIT_SECONDS,
        cadence=poll_every(RELAY_CONNECT_POLL_SECONDS),
        write=write,
    )


def wait_for_connection(timeout_seconds: float) -> bool:
    """Announce, then wait for this machine's relay heartbeat."""
    announce_connection()
    check = importlib.import_module("yoke_core.engines.doctor_hc_session_relay")
    return check.wait_for_connected_relay(
        timeout_seconds, poll_seconds=RELAY_CONNECT_POLL_SECONDS
    )


def status_command(environment: str | None) -> str:
    scope = f" --env {environment}" if environment else ""
    return f"yoke{scope} relay status"


def pending_heartbeat(environment: str | None) -> dict[str, object]:
    """The ``install_health`` pending entry for a relay not yet heard from."""
    return {
        "detail": (
            "machine relay installed; its first heartbeat had not arrived "
            f"within {RELAY_CONNECT_WAIT_SECONDS} seconds"
        ),
        "checks": [RELAY_HEALTH_CHECK],
        "next_action": (
            f"Run `{status_command(environment)}`; it shows the relay connected "
            "once its release pin and restart finish."
        ),
    }


__all__ = [
    "RELAY_CONNECT_POLL_SECONDS",
    "RELAY_CONNECT_WAIT_SECONDS",
    "RELAY_HEALTH_CHECK",
    "RELAY_INSTALL_TIMEOUT_SECONDS",
    "RELAY_STATUS_TIMEOUT_SECONDS",
    "WaitForConnection",
    "announce_connection",
    "announce_install",
    "pending_heartbeat",
    "status_command",
    "wait_for_connection",
]
