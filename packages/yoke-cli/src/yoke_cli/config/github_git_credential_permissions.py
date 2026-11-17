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
    """Refuse a credential directory others can write (or read, when private)."""
    try:
        info = path.lstat()
    except OSError as exc:
        raise error_type(f"GitHub App credential directory is missing: {path}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise error_type(f"GitHub App credential parent must be a directory: {path}")
    check = (owner_private_path.is_owner_private_directory if require_private
             else owner_private_path.is_others_unwritable_directory)
    if not check(path):
        repair = (_directory_repair() if require_private else
                  "remove other users' write access" if _WINDOWS else
                  "set directory permissions to 700")
        raise error_type(
            f"GitHub App credential directory permissions are unsafe: {path}; "
            f"{repair}, then retry"
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
