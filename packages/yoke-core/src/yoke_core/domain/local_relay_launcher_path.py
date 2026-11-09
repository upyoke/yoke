"""Locate the installed launcher used by a local-universe relay."""
import os
import sys
from pathlib import Path
from yoke_core.domain.launcher_locations import LAUNCHER_FILENAME, TARGET_PRIORITY

def local_launcher_candidates() -> tuple[Path, ...]:
    """Absolute launcher paths this machine may hold, best candidate first."""
    candidates = [
        Path(directory).expanduser() / LAUNCHER_FILENAME
        for directory, _label in TARGET_PRIORITY
    ]
    # A pipx or virtualenv install owns a console script beside its
    # interpreter even when no canonical shim was ever written.
    # Preserve the venv path: resolving its Python symlink moves to the base
    # interpreter, whose directory does not own this install's console script.
    candidates.append(Path(sys.executable).absolute().parent / LAUNCHER_FILENAME)
    unique: list[Path] = []
    for candidate in candidates:
        if candidate.is_absolute() and candidate not in unique:
            unique.append(candidate)
    return tuple(unique)



def local_launcher_ready(launcher: Path) -> bool:
    """Whether launchd could actually execute this launcher."""
    return launcher.is_file() and os.access(launcher, os.X_OK)



def local_launcher_path() -> Path:
    """The launcher a local relay runs, whether or not it is installed yet.

    Returning the leading candidate rather than raising keeps the launchd
    document computable on a machine with no launcher, so status reports the
    plist as stale and the install refuses by name instead of both crashing.
    """
    candidates = local_launcher_candidates()
    for candidate in candidates:
        if local_launcher_ready(candidate):
            return candidate
    return candidates[0]

