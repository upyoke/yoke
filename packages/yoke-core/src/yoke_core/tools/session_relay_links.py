"""Replace directory links under the relay's release pin lock."""

from pathlib import Path
import uuid

from yoke_contracts.platform_links import link
from yoke_contracts.platform_fs import remove_tree
from yoke_contracts.owner_private_path import create_owner_private_directory


def create_relay_directory(path: Path) -> Path:
    """Create missing relay ancestors with private ACLs before writing state."""
    if not path.parent.exists():
        create_relay_directory(path.parent)
    return create_owner_private_directory(path)


def remove_link(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
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
        if path.exists() or path.is_symlink():
            path.rename(previous)
        try:
            temporary.rename(path)
            activated = True
        except OSError:
            if previous.exists() or previous.is_symlink():
                previous.rename(path)
            raise
    finally:
        remove_link(temporary)
        if activated:
            remove_link(previous)
