"""Locate the installed launcher used by a local-universe relay."""
import os
import sys
from pathlib import Path
from yoke_core.domain.launcher_locations import LAUNCHER_FILENAME, TARGET_PRIORITY

#: Windows names: the installer writes a ``yoke.cmd`` shim into the canonical
#: directory, while a pipx or virtualenv install owns ``Scripts\yoke.exe``.
WINDOWS_SHIM_FILENAME = "yoke.cmd"
WINDOWS_SCRIPT_FILENAME = "yoke.exe"
_WINDOWS = os.name == "nt"


def local_launcher_candidates() -> tuple[Path, ...]:
    """Absolute launcher paths this machine may hold, best candidate first."""
    shim = WINDOWS_SHIM_FILENAME if _WINDOWS else LAUNCHER_FILENAME
    script = WINDOWS_SCRIPT_FILENAME if _WINDOWS else LAUNCHER_FILENAME
    candidates = [
        Path(directory).expanduser() / shim for directory, _label in TARGET_PRIORITY
    ]
    # A pipx or virtualenv install owns a console script beside its
    # interpreter even when no canonical shim was ever written.
    # Preserve the venv path: resolving its Python symlink moves to the base
    # interpreter, whose directory does not own this install's console script.
    candidates.append(Path(sys.executable).absolute().parent / script)
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

