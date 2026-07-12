"""Durable proof that one onboarding apply created a checkout directory."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import uuid
from typing import Any, Mapping


MARKER_NAME = "yoke-onboard-created.json"


def mark_created(root: Path) -> dict[str, Any] | None:
    """Create an owner-only marker through an opened checkout directory."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0,
    )
    try:
        descriptor = os.open(root, flags)
    except OSError:
        return None
    try:
        return mark_created_fd(descriptor)
    finally:
        os.close(descriptor)


def mark_created_fd(root_descriptor: int) -> dict[str, Any] | None:
    """Create a marker relative to an already-opened checkout inode."""

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0,
    )
    try:
        git_descriptor = os.open(".git", directory_flags, dir_fd=root_descriptor)
    except OSError:
        return None
    token = uuid.uuid4().hex
    marker_flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        marker_descriptor = os.open(
            MARKER_NAME, marker_flags, 0o600, dir_fd=git_descriptor,
        )
    except FileExistsError:
        os.close(git_descriptor)
        return None
    except OSError:
        os.close(git_descriptor)
        return None
    try:
        os.fchmod(marker_descriptor, 0o600)
        os.write(marker_descriptor, json.dumps({"token": token}).encode("utf-8"))
        os.fsync(marker_descriptor)
    except OSError:
        try:
            os.unlink(MARKER_NAME, dir_fd=git_descriptor)
        except OSError:
            pass
        return None
    finally:
        os.close(marker_descriptor)
        os.close(git_descriptor)
    root_info = os.fstat(root_descriptor)
    return {"device": root_info.st_dev, "inode": root_info.st_ino, "token": token}


def capture(root: Path) -> dict[str, Any] | None:
    """Return exact directory identity + marker token, or None fail-closed."""

    marker = root / ".git" / MARKER_NAME
    try:
        root_info = root.lstat()
        marker_info = marker.lstat()
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or root.is_symlink()
            or not stat.S_ISREG(marker_info.st_mode)
            or marker.is_symlink()
            or stat.S_IMODE(marker_info.st_mode) & 0o077
            or marker_info.st_size > 1024
        ):
            return None
        payload = json.loads(marker.read_text(encoding="utf-8"))
        token = str(payload.get("token") or "") if isinstance(payload, dict) else ""
        if len(token) != 32 or any(
            character not in "0123456789abcdef" for character in token
        ):
            return None
    except (OSError, ValueError, UnicodeError):
        return None
    return {"device": root_info.st_dev, "inode": root_info.st_ino, "token": token}


def matches(root: Path, expected: Mapping[str, Any]) -> bool:
    current = capture(root)
    return bool(current and current == {
        "device": expected.get("device"),
        "inode": expected.get("inode"),
        "token": expected.get("token"),
    })


def refresh_snapshot(snapshot: Any) -> None:
    """Attach marker evidence after a run-created checkout becomes available."""

    selected = snapshot if isinstance(snapshot, dict) else {}
    provenance = selected.get("checkout_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    if not provenance.get("created_by_run") or provenance.get("ownership"):
        return
    checkout = str(provenance.get("path") or "")
    evidence = capture(Path(checkout).expanduser()) if checkout else None
    if evidence:
        provenance["ownership"] = evidence


__all__ = [
    "MARKER_NAME", "capture", "mark_created", "mark_created_fd", "matches",
    "refresh_snapshot",
]
