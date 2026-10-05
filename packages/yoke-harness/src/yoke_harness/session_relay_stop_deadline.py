"""Read the running relay service's termination allowance once at startup."""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import sys

from yoke_cli.config.session_relay_instance import (
    LAUNCHD_USER_DOMAIN,
    resolve_relay_instance,
)

# A short host allowance when the manager cannot answer; reserve time for exit.
DEFAULT_STOP_TIMEOUT_SECONDS = 5.0
STOP_MARGIN_FRACTION = 0.1
MAX_STOP_MARGIN_SECONDS = 1.0
STOP_QUERY_TIMEOUT_SECONDS = 3.0
_LOGGER = logging.getLogger(__name__)
_DURATION_UNITS = {"us": 0.000001, "ms": 0.001, "s": 1, "min": 60, "h": 3600}


def _systemd_seconds(value: str) -> float:
    """systemctl formats TimeoutStopUSec as a duration, despite its name."""
    tokens = re.findall(r"(\d+(?:\.\d+)?)\s*(us|ms|min|s|h)\b", value)
    if not tokens or re.sub(r"\d+(?:\.\d+)?\s*(?:us|ms|min|s|h)\b", "", value).strip():
        raise ValueError("service stop timeout is not a finite duration")
    return sum(float(number) * _DURATION_UNITS[unit] for number, unit in tokens)


def read_stop_settlement_seconds() -> float:
    """Use nearly all the loaded manager deadline, or a conservative default.

    Read loaded service state instead of its file, so systemd overrides and
    launchd's effective default are included. An unavailable or unbounded
    timeout retains a bounded drain and names the diagnostic recovery.
    """
    timeout = DEFAULT_STOP_TIMEOUT_SECONDS
    try:
        instance = resolve_relay_instance()
        if sys.platform == "linux":
            argv = [
                "systemctl",
                "--user",
                "show",
                f"{instance.label}.service",
                "--property=TimeoutStopUSec",
                "--value",
            ]
        elif sys.platform == "darwin":
            argv = [
                "launchctl",
                "print",
                f"{LAUNCHD_USER_DOMAIN}/{os.getuid()}/{instance.label}",
            ]
        else:
            raise ValueError("this OS has no supported service deadline reader")
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=STOP_QUERY_TIMEOUT_SECONDS,
        )
        if result.returncode:
            raise ValueError("service manager could not read the loaded relay")
        if sys.platform == "linux":
            observed = _systemd_seconds(result.stdout.strip())
        else:
            match = re.search(
                r"^\s*exit timeout = (\d+)\s*$", result.stdout, re.MULTILINE
            )
            if match is None:
                raise ValueError("launchd omitted the exit timeout")
            observed = float(match[1])
        if not math.isfinite(observed) or observed <= 0:
            raise ValueError("service stop timeout is unbounded or invalid")
        timeout = observed
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        _LOGGER.warning(
            "relay_stop_deadline_unavailable: %s; using %gs; inspect the loaded "
            "relay with systemctl --user show or launchctl print, then restart it",
            exc,
            timeout,
        )
    margin = min(MAX_STOP_MARGIN_SECONDS, timeout * STOP_MARGIN_FRACTION)
    return timeout - margin
