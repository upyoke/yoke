"""Shared filesystem guards and atomic replacement for local writers."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile


def first_symlink_component(
    root: Path,
    target: Path,
    *,
    include_leaf: bool = False,
) -> Path | None:
    """Return the first symlink below *root* crossed by *target*, if any."""
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"target {target} is outside root {root}") from exc
    parts = relative.parts if include_leaf else relative.parts[:-1]
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            return current
    return None


def atomic_replace_bytes(
    target: Path,
    payload: bytes,
    *,
    mode: int = 0o644,
) -> None:
    """Atomically replace *target* through an unpredictable sibling file."""
    selected_mode = mode
    try:
        target_info = target.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISREG(target_info.st_mode):
            selected_mode = stat.S_IMODE(target_info.st_mode)
        elif stat.S_ISLNK(target_info.st_mode):
            try:
                effective_info = target.stat()
            except OSError:
                pass
            else:
                if stat.S_ISREG(effective_info.st_mode):
                    selected_mode = stat.S_IMODE(effective_info.st_mode)
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
        )
        temporary = Path(raw_temporary)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchmod(descriptor, selected_mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, target)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = ["atomic_replace_bytes", "first_symlink_component"]
