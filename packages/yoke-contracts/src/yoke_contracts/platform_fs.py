"""Bounded removal of local trees, including Windows read-only files."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import time


def remove_tree(path: str | Path) -> None:
    """Remove a tree without following root symlinks or junctions.

    Read-only entries are made writable. A still-locked path is named after a
    short bounded retry; callers must close the named file and retry.
    """
    selected = Path(path)

    def writable_retry(function, failed, exc_info):
        entry = Path(failed)
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            raise exc_info[1]
        os.chmod(failed, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        function(failed)

    for attempt in range(4):
        try:
            if selected.is_symlink():
                selected.unlink()
            elif getattr(selected, "is_junction", lambda: False)():
                selected.rmdir()
            elif selected.exists():
                shutil.rmtree(selected, onerror=writable_retry)
            return
        except FileNotFoundError:
            if not os.path.lexists(selected):
                return
        except OSError as exc:
            if attempt == 3:
                raise OSError(f"remove_tree_locked: {exc.filename or selected}; close the file or its owning process and retry: {exc}") from exc
        time.sleep(0.05 * (attempt + 1))


__all__ = ["remove_tree"]
