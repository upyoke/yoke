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

from yoke_core.domain.local_relay_launcher_path import (
    local_launcher_candidates,
    local_launcher_path,
    local_launcher_ready,
)

from yoke_cli.config.install_advice import install_command

from pathlib import Path

from yoke_contracts.refusal_recovery import compose_refusal


#: Refusal code for a local relay whose machine has no installed launcher.
LOCAL_LAUNCHER_MISSING = "relay_local_launcher_missing"


#: The one recovery for that refusal, named wherever the refusal is rendered.
def local_launcher_recovery() -> str:
    return f"install the released CLI with `{install_command()}`, then retry the relay install"


def local_launcher_missing_message(launcher: Path) -> str:
    """Name what the local relay needs and how to supply it."""
    return compose_refusal(
        f"the local universe relay runs this machine's installed Yoke, and no launcher is installed at {launcher}.",
        recovery=f"{local_launcher_recovery()}.",
    )


__all__ = [
    "LOCAL_LAUNCHER_MISSING",
    "local_launcher_recovery",
    "local_launcher_candidates",
    "local_launcher_missing_message",
    "local_launcher_path",
    "local_launcher_ready",
]
