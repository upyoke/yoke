"""Owner-only permission checks for GitHub App credential files."""

from __future__ import annotations

if __package__:
    from yoke_contracts import windows_private_directory
else:
    import _yoke_windows_private_directory as windows_private_directory

import os
from pathlib import Path
import stat


def assert_secure_parent(
    path: Path,
    error_type: type[RuntimeError],
    *,
    require_private: bool = True,
) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise error_type(f"GitHub App credential directory is missing: {path}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise error_type(f"GitHub App credential parent must be a directory: {path}")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise error_type(
            f"GitHub App credential directory is not owned by the current user: {path}"
        )
    forbidden_mode = 0o077 if require_private else 0o022
    if os.name == "nt" and not windows_private_directory.is_private_directory(path):
        raise error_type(
            f"GitHub App credential directory Windows permissions are unsafe: {path}"
        )
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & forbidden_mode:
        raise error_type(
            f"GitHub App credential directory permissions are unsafe: {path}; "
            "set directory permissions to 700, then retry"
        )


def assert_owner_only_file(
    info: os.stat_result,
    path: Path,
    error_type: type[RuntimeError],
) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise error_type(f"GitHub App credential must be a regular file: {path}")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise error_type(
            f"GitHub App credential is not owned by the current user: {path}"
        )
    if os.name == "nt" and not windows_private_directory.is_private_file(path):
        raise error_type(
            f"GitHub App credential Windows permissions are unsafe: {path}"
        )
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        raise error_type(
            f"GitHub App credential permissions must be 0600: {path}"
        )


__all__ = ["assert_owner_only_file", "assert_secure_parent"]
