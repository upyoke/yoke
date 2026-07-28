"""Client-safe settings contract for a serially controlled test machine."""

from __future__ import annotations

import re
from typing import Any, Mapping


_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_REMOTE_USER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")
_SETTING_KEYS = frozenset({"resource_name", "host", "user", "operating_notes"})


class TestMachineCapabilityError(ValueError):
    """The test-machine declaration or execution contract is invalid."""


def validate_test_machine_resource_name(value: Any) -> str:
    """Return one canonical resource name or reject an unsafe label."""
    normalized = str(value or "").strip()
    if not _RESOURCE_NAME.fullmatch(normalized):
        raise TestMachineCapabilityError("resource_name is not a safe resource label")
    return normalized


def validate_test_machine_settings(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return the canonical, non-secret settings document."""
    if set(payload) != _SETTING_KEYS:
        missing = sorted(_SETTING_KEYS - set(payload))
        unknown = sorted(set(payload) - _SETTING_KEYS)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise TestMachineCapabilityError(
            "test-machine settings require exactly resource_name, host, user, "
            "and operating_notes (" + "; ".join(detail) + ")"
        )
    values = {key: str(payload[key] or "").strip() for key in _SETTING_KEYS}
    values["resource_name"] = validate_test_machine_resource_name(
        values["resource_name"]
    )
    host = values["host"]
    if not host or len(host) > 253 or any(ch.isspace() for ch in host):
        raise TestMachineCapabilityError("host must be a non-empty host name")
    if not _REMOTE_USER.fullmatch(values["user"]):
        raise TestMachineCapabilityError("user is not a safe remote user name")
    if len(values["operating_notes"]) > 500:
        raise TestMachineCapabilityError(
            "operating_notes must be at most 500 characters"
        )
    return {key: values[key] for key in sorted(values)}


__all__ = [
    "TestMachineCapabilityError",
    "validate_test_machine_resource_name",
    "validate_test_machine_settings",
]
