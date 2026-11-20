"""How long setup waits on the machine relay, and what it says while it waits.

A first served-release install builds a fresh venv and pip-installs the
release wheels; on native Windows that alone has taken close to six minutes.
After the installer returns, the relay may still pin a release and restart
before its first heartbeat. Setup waits for both, announces each wait as a
designed wait, and reports a heartbeat that has not arrived as pending with
its next step rather than as a failed check.
"""

from __future__ import annotations

import importlib
from typing import Callable

from yoke_contracts.designed_wait import announce_designed_wait, poll_every


#: Covers a first served-release install on native Windows (observed 349 s).
RELAY_INSTALL_TIMEOUT_SECONDS = 900
#: Reading status inspects the user service and shakes hands with the plane.
RELAY_STATUS_TIMEOUT_SECONDS = 60
#: Covers the relay pinning a release and restarting before its first heartbeat.
RELAY_CONNECT_WAIT_SECONDS = 90
#: How often the heartbeat wait reads the relay's connection.
RELAY_CONNECT_POLL_SECONDS = 1.0
#: The ``install_health`` check a pending heartbeat stands in for.
RELAY_HEALTH_CHECK = "session-relay"

WaitForConnection = Callable[[float], bool]


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
