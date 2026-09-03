"""Wire contracts shared by Pack catalog, API, CLI, and project receipts."""

from __future__ import annotations

import re
from typing import Any, Mapping

PACK_DESCRIPTOR_SCHEMA = 2
PACK_BUNDLE_SCHEMA = 2
PACK_RECEIPT_SCHEMA = 3
PACK_RECEIPT_PREVIOUS_SCHEMAS = frozenset({1, 2})
PACKS_SOURCE = "packs"
PACK_RECEIPT_REL = ".yoke/packs.json"
PACK_PREREQUISITE_OS_KEYS = frozenset({"darwin", "linux", "windows"})

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_EXECUTABLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def validate_pack_prerequisites(value: Any) -> list[dict[str, Any]]:
    """Return a detached prerequisite list or raise a contract error."""
    if not isinstance(value, list):
        raise ValueError("prerequisites must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {
            "tool",
            "minimum_version",
            "probe",
            "install",
        }:
            raise ValueError(
                "each prerequisite must declare tool, minimum_version, "
                "probe, and install"
            )
        tool = raw.get("tool")
        minimum = raw.get("minimum_version")
        probe = raw.get("probe")
        install = raw.get("install")
        if not isinstance(tool, str) or not _TOOL_NAME.fullmatch(tool):
            raise ValueError("prerequisite tool names must be lowercase slugs")
        if tool in seen:
            raise ValueError(f"prerequisite tool {tool!r} is repeated")
        seen.add(tool)
        if not isinstance(minimum, str) or not _VERSION.fullmatch(minimum):
            raise ValueError(f"prerequisite {tool!r} minimum_version must be x.y.z")
        if not isinstance(probe, Mapping) or set(probe) != {
            "executable",
            "version_args",
        }:
            raise ValueError(f"prerequisite {tool!r} probe is invalid")
        executable = probe.get("executable")
        version_args = probe.get("version_args")
        if (
            not isinstance(executable, str)
            or not _EXECUTABLE_NAME.fullmatch(executable)
            or not isinstance(version_args, list)
            or not version_args
            or any(not _safe_text(arg) for arg in version_args)
        ):
            raise ValueError(f"prerequisite {tool!r} probe is invalid")
        if (
            not isinstance(install, Mapping)
            or set(install) != PACK_PREREQUISITE_OS_KEYS
        ):
            raise ValueError(
                f"prerequisite {tool!r} install must cover darwin, linux, and windows"
            )
        if any(not _safe_text(recipe) for recipe in install.values()):
            raise ValueError(f"prerequisite {tool!r} install recipe is invalid")
        normalized.append(
            {
                "tool": tool,
                "minimum_version": minimum,
                "probe": {
                    "executable": executable,
                    "version_args": list(version_args),
                },
                "install": {key: str(install[key]) for key in sorted(install)},
            }
        )
    return normalized


def _safe_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and "\n" not in value
        and "\r" not in value
        and "\x00" not in value
    )


__all__ = [
    "PACK_BUNDLE_SCHEMA",
    "PACK_DESCRIPTOR_SCHEMA",
    "PACK_PREREQUISITE_OS_KEYS",
    "PACK_RECEIPT_REL",
    "PACK_RECEIPT_PREVIOUS_SCHEMAS",
    "PACK_RECEIPT_SCHEMA",
    "PACKS_SOURCE",
    "validate_pack_prerequisites",
]
