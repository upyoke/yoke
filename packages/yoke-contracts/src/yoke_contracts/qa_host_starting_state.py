"""Declared OS package state for one exploratory QA mission."""

from __future__ import annotations

import re
from typing import Any

_PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?\Z")
_PROTECTED = frozenset(
    {"apt", "dpkg", "sudo", "openssh-server", "python3", "python3-minimal"}
)


def validate_host_starting_state(raw: Any) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"os_packages"}:
        raise ValueError("host_starting_state requires an os_packages object")
    packages = raw["os_packages"]
    if not isinstance(packages, dict) or set(packages) - {"present", "absent"}:
        raise ValueError("os_packages accepts only present and absent package lists")
    normalized = {}
    for state in ("present", "absent"):
        values = packages.get(state, [])
        if (
            not isinstance(values, list)
            or len(values) > 32
            or any(
                not isinstance(value, str) or not _PACKAGE.fullmatch(value)
                for value in values
            )
            or len(set(values)) != len(values)
        ):
            raise ValueError(
                f"os_packages.{state} requires at most 32 unique package names"
            )
        if state == "absent" and _PROTECTED.intersection(
            value.split(":")[0] for value in values
        ):
            raise ValueError(
                "os_package_protected: the QA transport and package manager must remain installed"
            )
        normalized[state] = sorted(values)
    if set(normalized["present"]) & set(normalized["absent"]):
        raise ValueError(
            "os_package_conflict: a package cannot be both present and absent"
        )
    return {"os_packages": normalized}
