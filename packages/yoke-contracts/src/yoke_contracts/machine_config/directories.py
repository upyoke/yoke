"""Private directory creation and short temp bases for machine state."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def create_private_directory(path: str | Path) -> Path:
    """Create every missing ancestor with mode 0700, preserving existing modes.

    ``Path.mkdir(parents=True)`` applies its mode only to the final directory.
    Existing directories remain subject to their caller's ownership and mode
    checks; creation must not silently repair an unsafe installation.
    """
    selected = Path(path).expanduser()
    try:
        selected.mkdir(mode=0o700)
    except FileNotFoundError:
        create_private_directory(selected.parent)
        return create_private_directory(selected)
    except FileExistsError:
        if not selected.is_dir():
            raise
    else:
        selected.chmod(0o700, follow_symlinks=False)
    return selected


def shortest_temp_directory() -> Path | None:
    """Return the shortest writable temp base: ``tempfile.gettempdir()`` or ``/tmp``.

    Unix-socket paths have a small byte limit, and a ``TMPDIR`` under a long
    machine home can exceed it on its own. ``None`` means neither is writable.
    """
    bases = {
        os.fsencode(candidate): candidate
        for candidate in (Path(tempfile.gettempdir()), Path("/tmp"))
        if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)
    }
    if not bases:
        return None
    return bases[min(bases, key=lambda encoded: (len(encoded), encoded))]
