"""The installed Yoke launcher a local-universe relay runs.

A relay bound to an https control plane follows the release that plane serves:
it pins that release beside a relay-owned Python and launchd runs the pinned
executable. A relay bound to a local universe has no served release to follow,
because the machine running the relay is also the machine serving the control
plane -- there is no remote build to fetch, no wheel index to fetch it from,
and no version skew between them to converge. It runs that machine's own
installed launcher instead, so the relay serves whatever Yoke the operator has
installed and upgrades with it.

Resolution deliberately ignores ``PATH``. launchd starts the relay with an
environment that has nothing to do with the login shell that installed it, and
a launcher path that changed between the two would make an unchanged install
look stale on every status read. The canonical install locations and the
running interpreter's own script directory are both stable across that
boundary.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from yoke_core.tools.install_yoke_launcher_core import (
    LAUNCHER_FILENAME,
    TARGET_PRIORITY,
)


#: Refusal code for a local relay whose machine has no installed launcher.
LOCAL_LAUNCHER_MISSING = "relay_local_launcher_missing"

#: The one recovery for that refusal, named wherever the refusal is rendered.
LOCAL_LAUNCHER_RECOVERY = (
    "install it with `python3 -m yoke_core.tools.install_yoke_launcher`, "
    "then retry the relay install"
)


def local_launcher_candidates() -> tuple[Path, ...]:
    """Absolute launcher paths this machine may hold, best candidate first."""
    candidates = [
        Path(directory).expanduser() / LAUNCHER_FILENAME
        for directory, _label in TARGET_PRIORITY
    ]
    # A pipx or virtualenv install owns a console script beside its
    # interpreter even when no canonical shim was ever written.
    candidates.append(Path(sys.executable).resolve().parent / LAUNCHER_FILENAME)
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


def local_launcher_missing_message(launcher: Path) -> str:
    """Name what the local relay needs and how to supply it."""
    return (
        "the local universe relay runs this machine's installed Yoke, and no "
        f"launcher is installed at {launcher}. Recovery: {LOCAL_LAUNCHER_RECOVERY}."
    )


__all__ = [
    "LOCAL_LAUNCHER_MISSING",
    "LOCAL_LAUNCHER_RECOVERY",
    "local_launcher_candidates",
    "local_launcher_missing_message",
    "local_launcher_path",
    "local_launcher_ready",
]
