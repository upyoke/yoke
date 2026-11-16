"""Durable proof that one onboarding apply created a checkout directory."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import uuid
from typing import Any, Mapping

from yoke_contracts.owner_private_path import (
    is_owner_private_file,
    write_owner_private,
)


MARKER_NAME = "yoke-onboard-created.json"


def mark_created(root: Path) -> dict[str, Any] | None:
    """Create an owner-only marker inside a checkout this run just created.

    Returns the checkout identity and marker token, or ``None`` when the
    checkout is not a real directory with a real ``.git`` directory or a
    marker already exists (fail closed: no ownership is claimed).
    """

    git_dir = root / ".git"
    marker = git_dir / MARKER_NAME
    try:
        root_info = root.lstat()
        git_info = git_dir.lstat()
    except OSError:
        return None
    if not (_plain_directory(root_info) and _plain_directory(git_info)):
        return None
    if os.path.lexists(marker):
        return None
    token = uuid.uuid4().hex
    try:
        write_owner_private(marker, json.dumps({"token": token}))
    except OSError:
        return None
    return {"device": root_info.st_dev, "inode": root_info.st_ino, "token": token}


def _plain_directory(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISDIR(info.st_mode) and not (
        getattr(info, "st_file_attributes", 0) & reparse
    )


def capture(root: Path) -> dict[str, Any] | None:
    """Return exact directory identity + marker token, or None fail-closed."""

    marker = root / ".git" / MARKER_NAME
    try:
        root_info = root.lstat()
        marker_info = marker.lstat()
        if (
            not _plain_directory(root_info)
            or not stat.S_ISREG(marker_info.st_mode)
            or not is_owner_private_file(marker)
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
    "MARKER_NAME", "capture", "mark_created", "matches",
    "refresh_snapshot",
]
