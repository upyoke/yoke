"""Create portable directory/file links with an explicit copy fallback."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


def link(target: str | Path, path: str | Path) -> str:
    """Return symlink/junction/copy; never overwrite an existing destination.

    A copied destination has no target identity: the caller must record its source.
    """
    source, destination = Path(target).absolute(), Path(path)
    if os.path.lexists(destination):
        raise FileExistsError(f"link_destination_exists: {destination}; remove the owned destination first")
    if not source.exists():
        raise FileNotFoundError(f"link_target_missing: {source}; restore the target and retry")
    try:
        destination.symlink_to(source, target_is_directory=source.is_dir())
        return "symlink"
    except OSError:
        if os.name != "nt":
            raise
    if source.is_dir():
        # cmd is required for its built-in mklink; pass paths through environment
        # expansion so shell metacharacters in paths cannot become commands.
        result = subprocess.run(
            ["cmd.exe", "/d", "/v:off", "/c", 'mklink /J "%YOKE_LINK_PATH%" "%YOKE_LINK_TARGET%"'],
            env={**os.environ, "YOKE_LINK_PATH": str(destination.absolute()),
                 "YOKE_LINK_TARGET": str(source)}, capture_output=True,
        )
        if result.returncode == 0:
            return "junction"
    try:
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        return "copy"
    except OSError as exc:
        raise OSError(f"link_creation_failed: {destination}; enable Windows Developer Mode for symlinks or grant copy access: {exc}") from exc


__all__ = ["link"]
