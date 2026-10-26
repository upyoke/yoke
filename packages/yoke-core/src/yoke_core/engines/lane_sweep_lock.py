"""One merged-lane sweep per checkout at a time.

The relay's periodic sweep, a merge's own sweep, and lane creation at the
worktree cap can all reach the same checkout at once. Two sweeps judging the
same lane would race to delete its worktree and branches, so each takes this
checkout's lock without waiting: a sweep that finds it held skips, because
the holder is already doing the same work.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from yoke_contracts import platform_file_lock

LOCK_FILE_NAME = "yoke-lane-sweep.lock"
SWEEP_LOCK_HELD = "another lane sweep is running in this checkout"


@contextmanager
def lane_sweep_lock(git_common_dir: str | Path) -> Iterator[bool]:
    """Yield whether this sweep holds the checkout's lock; never wait for it."""
    path = Path(git_common_dir) / LOCK_FILE_NAME
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0))
    try:
        try:
            platform_file_lock.acquire_exclusive_nonblocking(descriptor)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            platform_file_lock.release_exclusive(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["LOCK_FILE_NAME", "SWEEP_LOCK_HELD", "lane_sweep_lock"]
