"""Replace and read directory links under the relay's release pin lock.

The relay's ``release`` and ``venv`` pointers are links (directory junctions
on Windows). Setup reads them by their recorded target and never follows them:
a native Windows SSH session may refuse to traverse a junction its user made
(WinError 448, untrusted mount point).
"""

import os
from pathlib import Path
import uuid

from yoke_contracts.platform_links import is_link, link, link_target
from yoke_contracts.platform_links import remove_link as remove_link_itself
from yoke_contracts.platform_fs import remove_tree
from yoke_contracts.owner_private_path import create_owner_private_directory


def create_relay_directory(path: Path) -> Path:
    """Create missing relay ancestors with private ACLs before writing state."""
    if not path.parent.exists():
        create_relay_directory(path.parent)
    return create_owner_private_directory(path)


def relay_link_root(path: Path) -> Path:
    """The directory *path* serves: a link's recorded target, else *path*."""
    return link_target(path) if is_link(path) else Path(path)


def remove_link(path: Path) -> None:
    if is_link(path):
        remove_link_itself(path)
    elif os.path.lexists(path):
        remove_tree(path)


def activate_link(target: Path, path: Path) -> None:
    """Stage first, then swap with rollback; callers hold the install lock.

    Windows cannot replace a nonempty directory junction with os.replace.
    The pin lock keeps launchers out during the two renames.
    """
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    previous = temporary.with_name(temporary.name + "-previous")
    activated = False
    try:
        link(target, temporary)
        if os.path.lexists(path):
            path.rename(previous)
        try:
            temporary.rename(path)
            activated = True
        except OSError:
            if os.path.lexists(previous):
                previous.rename(path)
            raise
    finally:
        remove_link(temporary)
        if activated:
            remove_link(previous)
