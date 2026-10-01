"""Non-secret desktop route settings for a registered test machine."""

from __future__ import annotations

import re
from typing import Mapping

DESKTOP_PASSWORD_KEY = "desktop_password"
DESKTOP_SETTING_KEYS = frozenset(
    {
        "desktop_route",
        "desktop_protocol",
        "desktop_port",
        "desktop_user",
        "desktop_host",
    }
)


def validate_desktop_settings(settings: Mapping[str, str]) -> dict[str, str]:
    """Validate a complete route, keeping an undeclared desktop optional."""
    from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError

    present = DESKTOP_SETTING_KEYS.intersection(settings)
    if not present:
        return {}
    required = DESKTOP_SETTING_KEYS - {"desktop_host"}
    if not required <= present:
        raise TestMachineCapabilityError(
            "desktop_route_incomplete: declare desktop_route, desktop_protocol, "
            "desktop_port and desktop_user together"
        )
    route = {key: settings[key] for key in present}
    if route["desktop_route"] not in {"direct", "ssh-forward"}:
        raise TestMachineCapabilityError("desktop_route must be direct or ssh-forward")
    if route["desktop_protocol"] not in {"rdp", "vnc"}:
        raise TestMachineCapabilityError("desktop_protocol must be rdp or vnc")
    port = route["desktop_port"]
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise TestMachineCapabilityError(
            "desktop_port must be an integer from 1 to 65535"
        )
    route["desktop_port"] = str(int(port))
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9.@\\_-]{0,127}", route["desktop_user"]):
        raise TestMachineCapabilityError(
            "desktop_user must be a safe desktop login name"
        )
    host = route.get("desktop_host")
    if host is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", host):
        raise TestMachineCapabilityError(
            "desktop_host must be a literal host name or address"
        )
    return route
