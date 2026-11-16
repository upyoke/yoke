"""Owner-only permission checks for GitHub App credential files."""

from __future__ import annotations

if __package__:
    from yoke_contracts import owner_private_path
else:
    import _yoke_owner_private_path as owner_private_path

import os
from pathlib import Path
import stat

_WINDOWS = os.name == "nt"


def assert_secure_parent(
    path: Path,
    error_type: type[RuntimeError],
    *,
    require_private: bool = True,
) -> None:
    """Refuse a credential directory others can write (or read, when private).

    ``require_private=False`` admits a POSIX directory that others may read
    but not write. Windows has no such middle ground in Yoke's directory
    check, so both modes require the owner-private DACL there.
    """
    try:
        info = path.lstat()
    except OSError as exc:
        raise error_type(f"GitHub App credential directory is missing: {path}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise error_type(f"GitHub App credential parent must be a directory: {path}")
    if require_private or _WINDOWS:
        if not owner_private_path.is_owner_private_directory(path):
            raise error_type(
                f"GitHub App credential directory permissions are unsafe: {path}; "
                f"{_directory_repair()}, then retry"
            )
        return
    # POSIX-only middle ground (owner-writable, others may read): no shared
    # helper owns this policy, so it stays here.
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise error_type(
            f"GitHub App credential directory is not owned by the current user: {path}"
        )
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise error_type(
            f"GitHub App credential directory permissions are unsafe: {path}; "
            "set directory permissions to 700, then retry"
        )


def assert_owner_only_file(
    info: os.stat_result,
    path: Path,
    error_type: type[RuntimeError],
) -> None:
    """Refuse an opened credential file unless it is a private regular file."""
    if not stat.S_ISREG(info.st_mode):
        raise error_type(f"GitHub App credential must be a regular file: {path}")
    if not owner_private_path.is_owner_private_file(path):
        required = "owner-only" if _WINDOWS else "0600"
        raise error_type(
            f"GitHub App credential permissions must be {required}: {path}; "
            f"{_file_repair(path)}, then retry"
        )


def _directory_repair() -> str:
    if _WINDOWS:
        return (
            "remove inherited and other users' access so only your Windows "
            "account, SYSTEM and Administrators remain"
        )
    return "set directory permissions to 700"


def _file_repair(path: Path) -> str:
    if _WINDOWS:
        return (
            "remove other users' access so only your Windows account, SYSTEM "
            "and Administrators remain"
        )
    return f"run chmod 600 {path} as its owner"


__all__ = ["assert_owner_only_file", "assert_secure_parent"]
