"""Sealed-profile validation and content-free failure diagnostics.

This module is also embedded in the standard-library-only SSH capture program.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import tarfile


class ProfileArchiveError(ValueError):
    """A snapshot cannot be safely captured or restored."""

    def __init__(self, code: str, *, path=None, details=None):
        super().__init__(code)
        self.path = path
        self.details = details or {}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ProfileArchiveError(code)


def private_owned(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    require(info.st_uid == os.getuid(), "browser_profile_foreign_owner")
    require(not info.st_mode & 0o077, "browser_profile_not_private")
    require(
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
        "browser_profile_unsafe_entry",
    )


def literal_path(value: str) -> Path:
    selected = Path(value)
    require(
        selected.is_absolute()
        and str(selected) == value
        and ".." not in selected.parts
        and len(selected.parts) >= 3,
        "browser_profile_unsafe_path",
    )
    return selected


def no_symlink_parents(path: Path) -> None:
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "browser_profile_symlink_path")


def failure_details(step: str, exc: Exception) -> dict:
    """Never copy exception text: it can carry file names or profile bytes."""
    if isinstance(exc, OSError):
        message = (
            os.strerror(exc.errno)
            if exc.errno is not None
            else "Filesystem operation failed"
        )
    elif isinstance(exc, json.JSONDecodeError):
        message = f"Invalid manifest JSON at line {exc.lineno}, column {exc.colno}"
    elif isinstance(exc, UnicodeError):
        message = "Manifest is not valid UTF-8"
    elif isinstance(exc, (EOFError, tarfile.TarError)):
        message = "Archive is invalid or unreadable"
    else:
        message = "Invalid metadata value"
    if step == "profile_resolution":
        recovery = "Pass a valid project slug and an absolute sealed baseline path for the current test user's home."
    else:
        recovery = (
            "Inspect the selected path's ownership and read/write permissions as the test user; "
            "preserve the sealed capture and retry."
            if isinstance(exc, OSError)
            else "Preserve the rejected capture; re-capture the stopped signed-in profile through "
            "yoke test-machine golden-capture --component browser-profile into a new sibling snapshot. "
            "Never hand-edit the sealed manifest or archive."
        )
    return {
        "step": step,
        "error_class": type(exc).__name__,
        "message": message,
        "recovery": recovery,
    }


@contextmanager
def archive_step(step: str):
    try:
        yield
    except ProfileArchiveError:
        raise
    except (OSError, ValueError, EOFError, tarfile.TarError) as exc:
        raise ProfileArchiveError(
            f"browser_profile_{step}_failed", details=failure_details(step, exc)
        ) from None
