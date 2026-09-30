"""Private directory creation for machine state and credentials."""

from __future__ import annotations

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
