"""Shared filesystem guards and atomic replacement for local writers."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Callable, TypeVar

if __package__:
    from yoke_contracts import windows_private_directory
else:
    import _yoke_windows_private_directory as windows_private_directory

# Windows refuses to open, replace or delete a file while another handle holds
# it without delete sharing, or while a replaced file is still delete-pending,
# and reports that transient state as PermissionError. Elsewhere a
# PermissionError is a real permission failure and is never retried.
_RETRY_SHARING_VIOLATIONS = os.name == "nt"
SHARING_RETRY_SECONDS = 2.0
_Result = TypeVar("_Result")


def retry_sharing_violations(operation: Callable[[], _Result]) -> _Result:
    """Run a file operation, retrying Windows sharing violations briefly.

    Another process reading the file (an editor, Codex itself, an antivirus
    scan) holds it only for moments, so the operation is retried with backoff
    for SHARING_RETRY_SECONDS before the last PermissionError is raised.
    """
    if not _RETRY_SHARING_VIOLATIONS:
        return operation()
    deadline = time.monotonic() + SHARING_RETRY_SECONDS
    delay = 0.005
    while True:
        try:
            return operation()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)


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
    """Atomically replace *target* through an unpredictable sibling file.

    An existing regular file (or symlink target) keeps its mode. On Windows,
    where mode bits carry no access list, an owner-private existing file keeps
    a protected owner-only access list: the temporary is made private before
    the payload is written.
    """
    selected_mode = mode
    existing: Path | None = None
    try:
        target_info = target.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISREG(target_info.st_mode):
            selected_mode = stat.S_IMODE(target_info.st_mode)
            existing = target
        elif stat.S_ISLNK(target_info.st_mode):
            try:
                effective_info = target.stat()
            except OSError:
                pass
            else:
                if stat.S_ISREG(effective_info.st_mode):
                    selected_mode = stat.S_IMODE(effective_info.st_mode)
                    existing = target.resolve()
    keep_private = os.name == "nt" and existing is not None and _is_windows_private(existing)
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
        )
        temporary = Path(raw_temporary)
        if keep_private:
            windows_private_directory.make_private_file(temporary)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "nt":
            os.chmod(temporary, selected_mode)
        else:
            os.fchmod(descriptor, selected_mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        retry_sharing_violations(lambda: os.replace(temporary, target))
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _is_windows_private(existing: Path) -> bool:
    """Return whether an existing Windows file allows only trusted principals."""
    try:
        return windows_private_directory.is_private_file(existing)
    except OSError:
        return False


__all__ = [
    "SHARING_RETRY_SECONDS",
    "atomic_replace_bytes",
    "first_symlink_component",
    "retry_sharing_violations",
]
