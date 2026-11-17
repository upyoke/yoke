"""Minimal process environments without inheriting caller authority."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from collections.abc import Iterable


WINDOWS_SYSTEM_VARIABLES = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT")


def minimal_child_environment(
    path_entries: Iterable[str | os.PathLike[str]] = (),
) -> dict[str, str]:
    """Keep OS startup variables and executable directories, never caller secrets.

    Explicit entries come first so test shims and a child's virtualenv win.
    Split existing PATH values before passing them: each entry is one directory.
    """
    env = {name: os.environ[name] for name in WINDOWS_SYSTEM_VARIABLES if name in os.environ}
    directories = [*(os.fspath(path) for path in path_entries), str(Path(sys.executable).parent)]
    if system_root := env.get("SYSTEMROOT"):
        directories.append(str(Path(system_root) / "System32"))
    directories.extend(os.defpath.split(os.pathsep))
    env["PATH"] = os.pathsep.join(dict.fromkeys(path for path in directories if path))
    return env
