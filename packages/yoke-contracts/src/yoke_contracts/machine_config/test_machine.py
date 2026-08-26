"""Client-safe settings contract for a serially controlled test machine."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Any, Mapping


_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_REMOTE_USER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")
_SETTING_KEYS = frozenset({"resource_name", "host", "user", "operating_notes"})
# Declaring a golden baseline is what turns the destructive host reset into a
# restore instead of an enumeration, so its absence means the machine has opted
# out of that reset rather than that the settings are incomplete.
_OPTIONAL_SETTING_KEYS = frozenset({"golden_baseline_path"})


class TestMachineCapabilityError(ValueError):
    """The test-machine declaration or execution contract is invalid."""


def validate_test_machine_resource_name(value: Any) -> str:
    """Return one canonical resource name or reject an unsafe label."""
    normalized = str(value or "").strip()
    if not _RESOURCE_NAME.fullmatch(normalized):
        raise TestMachineCapabilityError("resource_name is not a safe resource label")
    return normalized


def validate_golden_baseline_path(value: Any) -> str:
    """Return one absolute, literal golden-baseline location.

    Containment is deliberately not decided here. The only home this location
    must stay clear of is the one the reset actually clears, and that home is
    resolved from the live host rather than from a settings document.
    """
    normalized = str(value or "").strip()
    selected = PurePosixPath(normalized)
    if (
        not normalized
        or "~" in normalized
        or "$" in normalized
        or normalized != str(selected)
        or not selected.is_absolute()
        or ".." in selected.parts
        or len(selected.parts) < 3
    ):
        raise TestMachineCapabilityError(
            "golden_baseline_path must be an absolute, literal, normalized path"
        )
    return normalized


def validate_test_machine_settings(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return the canonical, non-secret settings document."""
    present = set(payload)
    allowed = _SETTING_KEYS | _OPTIONAL_SETTING_KEYS
    if not _SETTING_KEYS <= present or not present <= allowed:
        missing = sorted(_SETTING_KEYS - present)
        unknown = sorted(present - allowed)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise TestMachineCapabilityError(
            "test-machine settings require exactly resource_name, host, user, "
            "and operating_notes, and optionally golden_baseline_path ("
            + "; ".join(detail)
            + ")"
        )
    values = {key: str(payload[key] or "").strip() for key in present}
    if values.get("golden_baseline_path"):
        values["golden_baseline_path"] = validate_golden_baseline_path(
            values["golden_baseline_path"]
        )
    else:
        values.pop("golden_baseline_path", None)
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
    "validate_golden_baseline_path",
    "validate_test_machine_resource_name",
    "validate_test_machine_settings",
]
