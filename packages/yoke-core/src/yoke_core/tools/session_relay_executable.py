"""Stable executable search path for a launchd machine relay."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import shutil

from yoke_contracts.harness_cli_manifest import harness_cli_executables

from yoke_core.tools.install_yoke_launcher_core import TARGET_PRIORITY


_RELAY_CLI_EXECUTABLES = harness_cli_executables()


def relay_executable_search_path(
    *,
    executable: Path,
    environ: Mapping[str, str],
) -> str:
    """Build a stable, bounded launchd path for Yoke and native CLIs."""
    candidates = [executable.expanduser().parent]
    ambient_path = environ.get("PATH", "")
    for command in _RELAY_CLI_EXECUTABLES:
        resolved = shutil.which(command, path=ambient_path)
        if resolved:
            candidates.append(Path(resolved).expanduser().parent)
    candidates.extend(Path(raw).expanduser() for raw, _label in TARGET_PRIORITY)
    candidates.extend(Path(raw) for raw in os.defpath.split(os.pathsep) if raw)
    unique: list[str] = []
    for candidate in candidates:
        value = str(candidate)
        if candidate.is_absolute() and value not in unique:
            unique.append(value)
    return os.pathsep.join(unique)


__all__ = ["relay_executable_search_path"]
