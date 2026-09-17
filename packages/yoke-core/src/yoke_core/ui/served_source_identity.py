"""The commit this UI server is serving its assets from.

A reviewer looking at a screenshot needs to know which candidate produced
it, and an assertion that the reviewer typed is not that answer. The
server publishes the commit itself, from the checkout its own module was
loaded out of — the same tree the static assets are read from — so the
value describes what is being served rather than whatever the machine's
ambient install happens to be.

A working tree with uncommitted changes is not those committed contents
and must never be published as if it were. Such a tree is named
``<sha>-dirty``: the base commit stays legible for a human, and any
consumer comparing against an exact commit fails closed on it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Union

from yoke_contracts.runtime_identity import SERVED_BUILD_DIRTY_SUFFIX

#: Re-exported so this module reads as one story; the value itself is the
#: publishing contract in :mod:`yoke_contracts.runtime_identity`, shared
#: with the independent readers that have to recognise it.
DIRTY_SUFFIX = SERVED_BUILD_DIRTY_SUFFIX


def _git(root: Path, *args: str) -> Optional[str]:
    """Run one read-only git command in *root*, or ``None`` if it cannot."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def served_build(checkout_root: Union[str, Path, None]) -> str:
    """Return the served commit, ``<sha>-dirty``, or ``""``.

    An empty answer means this server cannot say what it is serving — a
    packaged wheel, a tree that is not a git checkout, or a git that
    refused. Publishing nothing is the honest answer there; it is not the
    same as publishing a commit nobody can check.
    """
    if not checkout_root:
        return ""
    root = Path(checkout_root)
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        return ""
    sha = head.strip()
    if not sha:
        return ""
    status = _git(root, "status", "--porcelain")
    if status is None:
        # Whether the tree is clean could not be determined, so it cannot be
        # certified as the commit. Unverified is not clean.
        return f"{sha}{DIRTY_SUFFIX}"
    return sha if not status.strip() else f"{sha}{DIRTY_SUFFIX}"


def served_install() -> dict:
    """The install these assets are read from, as this package resolves it.

    The checkout this code was loaded out of is the tree the static assets
    are read from, so what it reports describes what is being served — not
    whatever install the machine happens to have on PATH.
    """
    import yoke_core
    from yoke_contracts.runtime_identity import detect_install

    return dict(detect_install(yoke_core.__file__))


def served_build_identity() -> str:
    """The served commit, for the mounted packet and the identity path alike.

    One resolver, because a host answering two different things about
    itself makes the cheaper answer worthless: the packet a reviewer reads
    on screen and the value a check reads over the wire are one reading.
    """
    return served_build(served_install().get("checkout_root"))


__all__ = [
    "DIRTY_SUFFIX",
    "served_build",
    "served_build_identity",
    "served_install",
]
