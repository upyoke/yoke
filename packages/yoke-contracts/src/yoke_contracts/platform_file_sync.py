"""Durability helpers for local filesystem metadata."""

from __future__ import annotations

import os
from pathlib import Path


def sync_directory(path: str | Path) -> None:
    """Persist directory metadata where the platform exposes that operation.

    Windows does not support opening a directory with ``os.open`` for
    ``fsync``. File contents are still flushed before their atomic replace;
    the containing-directory flush is therefore available only on POSIX.
    """
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["sync_directory"]
